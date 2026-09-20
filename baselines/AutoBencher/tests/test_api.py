import json
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from unittest.mock import patch

import httpx

from api import start_api


@contextmanager
def provider(statuses, payloads=None):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append((self.headers['Authorization'], json.loads(
                self.rfile.read(int(self.headers['Content-Length'])))))
            status = statuses[min(len(calls) - 1, len(statuses) - 1)]
            if status is None:
                self.close_connection = True
                return
            content = json.dumps({'choices': [{'message': {'content': 'answer'}}]}).encode()
            if payloads is not None:
                content = payloads[min(len(calls) - 1, len(payloads) - 1)]
            self.send_response(status)
            self.send_header('Content-Length', str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1', calls
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ApiTest(unittest.TestCase):
    def test_stream_retries_discard_partial_answers_and_preserve_usage(self):
        def event(delta, finish=None):
            return 'data: ' + json.dumps({'id': 'completion', 'model': 'gpt-5.6-sol',
                'choices': [{'index': 0, 'delta': delta, 'finish_reason': finish}]}) + '\n\n'
        usage = {'prompt_tokens': 42, 'completion_tokens': 70, 'total_tokens': 112,
                 'completion_tokens_details': {'reasoning_tokens': 60}}
        partial = event({'content': 'discard me'})
        complete = ': heartbeat\n\n' + event({'role': 'assistant'})
        complete += event({'reasoning_content': 'private reasoning'})
        complete += event({'content': '最终'}) + event({'content': '答案'}, 'stop')
        complete += 'data: ' + json.dumps({'choices': [], 'usage': usage}) + '\n\n'
        complete += 'data: [DONE]\n\n'
        payloads = [partial.encode(), (partial + 'data: [DONE]\n\n').encode(), complete.encode()]
        with provider([200], payloads) as (upstream, calls), TemporaryDirectory() as directory:
            root = Path(directory)
            target = {'base_url': upstream, 'api_key': 'secret', 'model': 'gpt-5.6-sol',
                      'rpm': 50, 'extra_body': {'stream': True, 'stream_options': {'include_usage': True},
                                               'reasoning_effort': 'high', 'max_tokens': 300000}}
            with patch('api.RateLimit') as rate_class:
                url, close = start_api(upstream, 'secret', 'deepseek-flash', {}, 42, root, test_taker=target)
                try:
                    with patch('api.time.sleep'), httpx.Client(trust_env=False) as client:
                        response = client.post(url + '/chat/completions', json={
                            'model': 'gpt-autobencher-target', 'messages': [{'role': 'user', 'content': 'Question'}],
                            'temperature': 0.01, 'n': 1})
                    self.assertEqual(response.status_code, 200)
                    result = response.json()
                    self.assertEqual(result['object'], 'chat.completion')
                    self.assertEqual(result['choices'][0], {'index': 0, 'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': '最终答案', 'reasoning_content': 'private reasoning'}})
                    self.assertEqual(result['usage'], usage)
                    self.assertEqual(len(calls), 3)
                    self.assertEqual(rate_class.return_value.reservation.call_count, 3)
                    self.assertTrue(all(body == calls[0][1] for _, body in calls))
                    self.assertEqual(calls[0][1]['seed'], 42)
                    self.assertEqual(calls[0][1]['reasoning_effort'], 'high')
                    logs = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
                    self.assertEqual([row['status'] for row in logs], [502, 502, 200])
                    self.assertEqual(logs[-1]['response'], result)
                finally:
                    close()

    def test_target_retries_are_limited_and_agent_is_not(self):
        with provider([503, 503, 200]) as (target_url, target_calls), provider([200]) as (agent_url, agent_calls), TemporaryDirectory() as directory:
            with patch('api.RateLimit') as rate_class:
                url, close = start_api(agent_url, 'agent-secret', 'deepseek-flash', {}, 42, Path(directory),
                    test_taker={'base_url': target_url, 'api_key': 'target-secret', 'model': 'gpt-5.6-sol',
                                'extra_body': {'reasoning_effort': 'high'}, 'rpm': 50})
                try:
                    with patch('api.time.sleep'), httpx.Client(trust_env=False) as client:
                        for model in ('gpt-autobencher', 'gpt-autobencher-target'):
                            self.assertEqual(client.post(url + '/chat/completions', json={'model': model}).status_code, 200)
                    self.assertEqual(len(target_calls), 3)
                    self.assertEqual(len(agent_calls), 1)
                    self.assertEqual(rate_class.return_value.reservation.call_count, 3)
                    self.assertEqual(rate_class.call_args.args[1], 50)
                finally:
                    close()

    def test_separate_routes(self):
        with provider([200]) as (ds_url, ds), provider([200]) as (qw_url, qw), TemporaryDirectory() as directory:
            root = Path(directory)
            url, close = start_api(ds_url, 'ds-secret', 'deepseek-flash',
                {'thinking': {'type': 'enabled'}, 'reasoning_effort': 'high', 'max_tokens': 300000},
                42, root, test_taker={'base_url': qw_url, 'api_key': 'qw-secret', 'model': 'qwen3.8-27b',
                'extra_body': {'enable_thinking': True, 'reasoning_effort': 'xhigh', 'max_tokens': 131072}})
            try:
                with httpx.Client(trust_env=False) as client:
                    for alias in ('gpt-autobencher', 'gpt-autobencher-target', 'gpt-autobencher'):
                        response = client.post(url + '/chat/completions', json={
                            'model': alias, 'messages': [{'role': 'user', 'content': 'Question'}],
                            'max_tokens': 50, 'temperature': 0.01})
                        self.assertEqual(response.status_code, 200)
                self.assertEqual(len(ds), 2)
                self.assertEqual(len(qw), 1)
                for calls, key, model, effort, budget in (
                    (ds, 'ds-secret', 'deepseek-flash', 'high', 300000),
                    (qw, 'qw-secret', 'qwen3.8-27b', 'xhigh', 131072)):
                    for auth, body in calls:
                        self.assertEqual(auth, 'Bearer ' + key)
                        self.assertEqual((body['model'], body['reasoning_effort'], body['max_tokens'], body['seed']),
                                         (model, effort, budget, 42))
                        self.assertEqual(body['messages'], [{'role': 'user', 'content': 'Question'}])
                        self.assertEqual(body['temperature'], 0.01)
                self.assertNotIn('thinking', qw[0][1])
                self.assertNotIn('enable_thinking', ds[0][1])
                self.assertEqual(ds[0][1]['thinking'], {'type': 'enabled'})
                self.assertIs(qw[0][1]['enable_thinking'], True)
                logs = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
                self.assertEqual([row['request'] for row in logs], [ds[0][1], qw[0][1], ds[1][1]])
            finally:
                close()

    def test_retries_and_original_single_provider(self):
        for statuses, expected_count, expected_status in (
            ([503, 200], 2, 200), ([None, 200], 2, 200),
            ([429], 3, 429), ([400], 1, 400)):
            with self.subTest(statuses=statuses), provider(statuses) as (upstream, calls), TemporaryDirectory() as directory:
                root = Path(directory)
                url, close = start_api(upstream, 'secret', 'original-model', {}, 42, root)
                try:
                    with patch('api.time.sleep'), httpx.Client(trust_env=False) as client:
                        response = client.post(url + '/chat/completions', json={'model': 'gpt-autobencher', 'max_tokens': 50})
                    self.assertEqual((response.status_code, len(calls)), (expected_status, expected_count))
                    self.assertTrue(all(body == {'model': 'original-model', 'max_tokens': 50, 'seed': 42} for _, body in calls))
                    logs = [json.loads(line) for line in (root / 'requests.jsonl').read_text().splitlines()]
                    self.assertEqual([row['attempt'] for row in logs], list(range(1, expected_count + 1)))
                finally:
                    close()


if __name__ == '__main__':
    unittest.main()
