"""Serve Claude Code's Messages protocol using LiteLLM's OpenAI adapter."""
import argparse
import hmac
import json
import logging
import os
from pathlib import Path
import time

os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'True'
os.environ['LITELLM_TELEMETRY'] = 'False'

from aiohttp import web
import litellm
from litellm.llms.anthropic.experimental_pass_through.messages.handler import anthropic_messages

litellm.use_chat_completions_url_for_anthropic_messages = True
litellm.suppress_debug_info = True
litellm.turn_off_message_logging = True
litellm.telemetry = False
logging.disable(logging.CRITICAL)


def completion_request(payload, token, upstream):
    payload = dict(payload)
    if payload.get('model') != 'gpt-5.6-sol':
        raise ValueError('Unexpected model')
    # OpenAI represents enabled reasoning with reasoning_effort. Keeping the
    # Anthropic token budget would make LiteLLM override the requested effort.
    payload.pop('thinking', None)
    output = dict(payload.pop('output_config', {}))
    output.pop('effort', None)
    if output:
        payload['output_config'] = output
    payload.update(model='openai/gpt-5.6-sol', reasoning_effort='high',
                   api_base=upstream, api_key=token, num_retries=0, timeout=600,
                   _skip_responses_api_bridge=True)
    return payload


def make_app(token, upstream, log_path):
    async def messages(request):
        provided = request.headers.get('x-api-key') or request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(provided, token):
            return web.json_response({'type': 'error', 'error': {'type': 'authentication_error', 'message': 'Invalid local credential'}}, status=401)
        event = dict(received=time.time(), path=request.path)
        response = None
        try:
            payload = await request.json()
            event.update(model=payload.get('model'), stream=bool(payload.get('stream')),
                         reasoning_effort='high', messages=len(payload.get('messages', [])),
                         tools=len(payload.get('tools', [])))
            result = await anthropic_messages(**completion_request(payload, token, upstream))
            if payload.get('stream'):
                response = web.StreamResponse(headers={'Content-Type': 'text/event-stream'})
                await response.prepare(request)
                async for chunk in result:
                    await response.write(chunk)
                await response.write_eof()
            else:
                response = web.json_response(result)
            event['status'] = 200
        except Exception as error:
            status = getattr(error, 'status_code', 500) or 500
            if isinstance(error, ValueError):
                status = 400
            event.update(status=status, error=type(error).__name__)
            body = {'type': 'error', 'error': {'type': 'api_error', 'message': f'API adapter: {type(error).__name__} (HTTP {status})'}}
            if response is not None and response.prepared:
                try:
                    await response.write(('event: error\ndata: ' + json.dumps(body) + '\n\n').encode())
                    await response.write_eof()
                except ConnectionError:
                    pass
            else:
                response = web.json_response(body, status=status)
        finally:
            event['finished'] = time.time()
            with log_path.open('a') as log:
                log.write(json.dumps(event) + '\n')
        return response

    app = web.Application(client_max_size=0)
    app.router.add_post('/v1/messages', messages)
    return app


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--secrets', type=Path, required=True)
    parser.add_argument('--log', type=Path, required=True)
    parser.add_argument('--host', default='10.253.240.1')
    parser.add_argument('--port', default=18963, type=int)
    parser.add_argument('--upstream', default='http://10.253.240.2:18962/v1')
    args = parser.parse_args()
    token = json.loads(args.secrets.read_text())['token']
    web.run_app(make_app(token, args.upstream, args.log), host=args.host, port=args.port,
                access_log=None, print=None)


if __name__ == '__main__':
    main()
