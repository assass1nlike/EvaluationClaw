import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

import litellm
import pytest

from local.eval_model_adapter import anthropic_messages, completion_request


def test_chat_request_retains_image_tool_history_and_high_effort(monkeypatch):
    captured = []

    async def complete(**kwargs):
        captured.append(kwargs)
        return litellm.ModelResponse(model='gpt-5.6-sol', choices=[{
            'index': 0, 'message': {'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': 'call_new', 'type': 'function', 'function': {'name': 'report', 'arguments': '{"colour":"blue"}'}}]},
            'finish_reason': 'tool_calls'}], usage={'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30})

    monkeypatch.setattr(litellm, 'acompletion', complete)
    image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aW1hZ2U='}}
    tool = {'name': 'report', 'input_schema': {'type': 'object', 'properties': {'colour': {'type': 'string'}}}}
    messages = [{'role': 'user', 'content': [{'type': 'text', 'text': 'Inspect this'}, image]},
                {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'call_old', 'name': 'report', 'input': {'colour': 'unknown'}}]},
                {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_old', 'content': [image]}]}]
    payload = {'model': 'gpt-5.6-sol', 'max_tokens': 4096, 'messages': messages,
               'system': 'Keep the original task.', 'tools': [tool],
               'thinking': {'type': 'enabled', 'budget_tokens': 1024}, 'output_config': {'effort': 'high'}}
    response = asyncio.run(anthropic_messages(**completion_request(payload, 'dummy-token', 'http://localhost/v1')))
    sent = captured[0]
    assert sent['model'] == 'openai/gpt-5.6-sol'
    assert sent['reasoning_effort'] == 'high' and sent['num_retries'] == 0
    assert sent['messages'][0] == {'role': 'system', 'content': 'Keep the original task.'}
    assert sent['messages'][1]['content'][1]['image_url']['url'] == 'data:image/png;base64,aW1hZ2U='
    assert sent['messages'][2]['tool_calls'][0]['id'] == 'call_old'
    assert sent['messages'][3]['tool_call_id'] == 'call_old'
    assert sent['messages'][3]['content'][0]['image_url']['url'] == 'data:image/png;base64,aW1hZ2U='
    assert sent['tools'][0]['function']['parameters'] == tool['input_schema']
    assert response['stop_reason'] == 'tool_use'
    assert response['content'][0]['input'] == {'colour': 'blue'}
    assert payload['thinking']['budget_tokens'] == 1024


def test_unknown_model_is_rejected():
    with pytest.raises(ValueError):
        completion_request({'model': 'different-model'}, 'secret', 'http://localhost/v1')


def test_actual_http_transport_preserves_high_and_image_in_chat():
    captured = []

    class Upstream(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            captured.append((self.path, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
            body = b'{"error":{"message":"Intentional test endpoint","type":"invalid_request_error"}}'
            self.send_response(400)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    payload = {'model': 'gpt-5.6-sol', 'max_tokens': 4096,
               'messages': [{'role': 'user', 'content': [
                   {'type': 'text', 'text': 'Inspect the image'},
                   {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aW1hZ2U='}}]}],
               'tools': [{'name': 'report', 'input_schema': {'type': 'object', 'properties': {}}}],
               'thinking': {'type': 'enabled', 'budget_tokens': 1024}, 'output_config': {'effort': 'high'}}
    try:
        with pytest.raises(litellm.BadRequestError):
            asyncio.run(anthropic_messages(**completion_request(payload, 'dummy-token', f'http://127.0.0.1:{server.server_port}/v1')))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert len(captured) == 1  # The adapter adds neither retries nor fallbacks.
    path, request = captured[0]
    assert path == '/v1/chat/completions'
    assert request['model'] == 'gpt-5.6-sol'
    assert request['reasoning_effort'] == 'high'
    assert request['tools'][0]['function']['name'] == 'report'
    assert request['messages'][0]['content'][1]['image_url']['url'] == 'data:image/png;base64,aW1hZ2U='
