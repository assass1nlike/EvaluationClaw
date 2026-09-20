"""Local OpenAI-compatible forwarding and request recording."""

from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread

import httpx

from rate_limit import RateLimit, SharedSlots


def collect_stream(response):
    """Assemble a text completion; an interrupted stream must be retried."""
    result, choices, data = {}, {}, []
    for line in response.iter_lines():
        if line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
        if line or not data:
            continue
        event, data = '\n'.join(data), []
        if event == '[DONE]':
            if not choices or any(c['finish_reason'] is None for c in choices.values()):
                raise httpx.RemoteProtocolError('Stream ended without finished choices')
            result['object'] = 'chat.completion'
            result['choices'] = [choices[i] for i in sorted(choices)]
            for choice in result['choices']:
                for key, value in choice['message'].items():
                    if isinstance(value, list):
                        choice['message'][key] = ''.join(value)
            return json.dumps(result).encode()
        try:
            chunk = json.loads(event)
        except ValueError as error:
            raise httpx.RemoteProtocolError('Invalid JSON in completion stream') from error
        if 'error' in chunk:
            raise httpx.RemoteProtocolError(json.dumps(chunk['error']))
        result.update({k: v for k, v in chunk.items() if k != 'choices' and v is not None})
        for part in chunk.get('choices', []):
            choice = choices.setdefault(part['index'], {
                'index': part['index'], 'message': {'role': 'assistant', 'content': None},
                'finish_reason': None,
            })
            for key, value in part.get('delta', {}).items():
                if key in ('content', 'reasoning_content', 'refusal') and value is not None:
                    if choice['message'].get(key) is None:
                        choice['message'][key] = []
                    choice['message'][key].append(value)
                elif key == 'role':
                    choice['message'][key] = value
            if part.get('finish_reason') is not None:
                choice['finish_reason'] = part['finish_reason']
    raise httpx.RemoteProtocolError('Completion stream disconnected before [DONE]')


def start_api(base_url, api_key, model, extra_body, seed, run_dir, test_taker=None, parallel=None):
    client = httpx.Client(timeout=300, limits=httpx.Limits(max_connections=256, max_keepalive_connections=128))
    records = (run_dir / 'requests.jsonl').open('a')
    record_lock = Lock()
    default = dict(base_url=base_url, api_key=api_key, model=model, extra_body=extra_body)
    limiter = None
    slots = {}
    for role, route in [('judge', default), ('target', test_taker)]:
        if route is None:
            continue
        identity = route['base_url'].rstrip('/') + '/' + route['model']
        cache = Path(__file__).resolve().parent / '.cache'
        digest = hashlib.sha256(identity.encode()).hexdigest()
        if role == 'target' and route.get('rpm'):
            limiter = RateLimit(cache / 'rate-limits' / (digest + '.json'), route['rpm'])
        if parallel:
            slots[role] = SharedSlots(cache / 'request-slots' / digest, parallel[role])

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/v1/chat/completions':
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            role = 'target' if test_taker and body['model'] == 'gpt-autobencher-target' else 'judge'
            route = test_taker if role == 'target' else default
            body.update(route['extra_body'])
            body.update(model=route['model'], seed=seed)
            for attempt in range(1, 4):
                gate = slots[role].slot() if role in slots else nullcontext()
                with gate:
                    quota = limiter.reservation() if limiter and role == 'target' else nullcontext(None)
                    with quota as mark_sent:
                        sent = None
                        api_headers = False
                        def trace(event, info):
                            nonlocal sent, api_headers
                            if event.endswith('send_request_headers.started'):
                                api_headers = info['request'].method == b'POST'
                            if event.endswith('send_request_headers.complete') and api_headers:
                                sent = time.time()
                                if mark_sent:
                                    mark_sent()
                        started = time.time()
                        try:
                            endpoint = route['base_url'].rstrip('/') + '/chat/completions'
                            options = dict(
                                headers={'Authorization': f"Bearer {route['api_key']}"}, json=body,
                                timeout=parallel.get('target_timeout', 300) if parallel and role == 'target' else 300,
                                extensions={'trace': trace},
                            )
                            if body.get('stream'):
                                with client.stream('POST', endpoint, **options) as response:
                                    status = response.status_code
                                    content = collect_stream(response) if status == 200 else response.read()
                            else:
                                response = client.post(endpoint, **options)
                                status, content = response.status_code, response.content
                        except httpx.HTTPError as error:
                            status = 502
                            content = json.dumps({'error': {'message': str(error)}}).encode()
                try:
                    payload = json.loads(content)
                except ValueError:
                    payload = content.decode(errors='replace')
                with record_lock:
                    records.write(json.dumps({
                        'started': started, 'sent': sent, 'seconds': time.time() - started,
                        'attempt': attempt, 'request': body, 'status': status, 'response': payload,
                    }, ensure_ascii=False) + '\n')
                    records.flush()
                if status not in (408, 409, 429) and status < 500:
                    break
                if attempt < 3:
                    time.sleep(2 ** (attempt - 1))
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            try:
                self.wfile.write(content)
            except (BrokenPipeError, ConnectionResetError):
                # The upstream response remains recorded if the caller disconnected.
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = False
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def close():
        server.shutdown()
        thread.join()
        server.server_close()
        client.close()
        records.close()

    return f'http://127.0.0.1:{server.server_port}/v1', close
