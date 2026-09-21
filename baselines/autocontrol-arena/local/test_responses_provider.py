"""Validate response filtering without sending API requests."""

from contextlib import nullcontext
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import httpx
from openai import APIError, APIStatusError, APITimeoutError, OpenAI
from openai.types.responses import Response, ResponseError

from local.responses_provider import invoke_responses, retry_delay


def response(model='gpt-5.6-sol', text='accepted', instructions='system', failed=False):
    result = Response(
        id='resp_test', created_at=0, model=model, object='response',
        status='failed' if failed else 'completed', instructions=instructions,
        reasoning={'effort': 'high', 'summary': 'auto'},
        parallel_tool_calls=False, tool_choice='auto', tools=[],
        output=[{'type': 'message', 'id': 'msg_test', 'role': 'assistant', 'status': 'completed',
                 'content': [{'type': 'output_text', 'text': text, 'annotations': []}]}],
        usage={'input_tokens': 10, 'output_tokens': 2, 'total_tokens': 12,
               'input_tokens_details': {'cached_tokens': 0, 'cache_write_tokens': 0},
               'output_tokens_details': {'reasoning_tokens': 1}},
    )
    if failed:
        result.error = ResponseError(code='server_error', message='Rejected by service')
    return result


class ResponseFilteringTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.tmp')
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {
            'AUTOCONTROL_ARENA_RESULTS_DIR': self.directory.name,
            'AUTOCONTROL_ARENA_TARGET_RPM': '45',
            'AUTOCONTROL_ARENA_TARGET_RATE_LIMIT_FILE': self.directory.name + '/rate',
            'AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES': '5',
            'AUTOCONTROL_ARENA_OMIT_TEMPERATURE': '0',
            'AUTOCONTROL_ARENA_TRANSIENT_RETRIES': '8',
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.slots = patch('local.request_rate.wait_for_slot').start()
        self.sleep = patch('local.responses_provider.time.sleep').start()
        self.addCleanup(patch.stopall)
        sdk = patch('local.responses_provider.OpenAI').start()
        self.client = MagicMock()
        sdk.return_value.__enter__.return_value = self.client

    def invoke(self, responses):
        self.client.responses.create.side_effect = [
            r if isinstance(r, Exception) or hasattr(r, '__enter__') else
            nullcontext([SimpleNamespace(type='response.' + r.status, response=r)]) for r in responses]
        return invoke_responses(
            [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'task'}],
            {'api_key': 'test', 'api_base_url': 'https://example.invalid/v1', 'model_name': 'gpt-5.6-sol'},
            return_usage=True,
        )

    def records(self, filename='responses-usage.jsonl'):
        return [json.loads(line) for line in (Path(self.directory.name) / filename).read_text().splitlines()]

    def test_rerouted_answer_is_discarded_and_all_attempts_are_counted(self):
        answer, usage = self.invoke([response('gpt-6-sol', 'wrong'), response()])
        self.assertEqual(answer, 'accepted')
        self.assertEqual(usage['total_tokens'], 12)
        self.assertEqual(self.client.responses.create.call_args_list[0], self.client.responses.create.call_args_list[1])
        self.assertEqual(self.slots.call_count, 2)
        records = self.records()
        self.assertEqual([r['accepted'] for r in records], [False, True])
        self.assertEqual(sum(r['usage']['total_tokens'] for r in records), 24)

    def test_model_retry_budget_is_bounded(self):
        with self.assertRaisesRegex(RuntimeError, 'model retries exhausted'):
            self.invoke([response('gpt-6-sol')] * 6)
        self.assertEqual(self.slots.call_count, 6)
        self.assertTrue(all(not r['accepted'] for r in self.records()))

    def test_temperature_can_be_omitted_for_azure_gateway(self):
        with patch.dict(os.environ, {'AUTOCONTROL_ARENA_OMIT_TEMPERATURE': '1'}):
            self.invoke([response()])
        self.assertNotIn('temperature', self.client.responses.create.call_args.kwargs)
        self.assertEqual(self.client.responses.create.call_args.kwargs['reasoning']['effort'], 'high')
        self.assertIsNone(self.records()[0]['requested_temperature'])

    def test_model_mismatch_can_be_deferred_without_retry(self):
        with patch.dict(os.environ, {'AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES': '0'}):
            with self.assertRaisesRegex(RuntimeError, 'model retries exhausted'):
                self.invoke([response('gpt-6-sol')])
        self.assertEqual(self.slots.call_count, 1)
        record, = self.records()
        self.assertEqual(record['rejection_reason'], 'model_mismatch')
        self.assertFalse(record['accepted'])

    def test_missing_instruction_echo_is_recorded_without_acceptance(self):
        with self.assertRaisesRegex(RuntimeError, 'system instructions'):
            self.invoke([response(instructions=None)])
        record, = self.records('rejected-responses.jsonl')
        self.assertEqual(record['requested_instructions'], 'system')
        self.assertIsNone(record['response']['instructions'])
        self.assertEqual(self.slots.call_count, 1)

    def test_service_rejection_is_not_automatically_repeated(self):
        rejected = response(failed=True)
        rejected.error = ResponseError.model_construct(code='cyber_policy', message='Rejected by service')
        rejected.output = None
        rejected.usage = None
        with self.assertRaisesRegex(RuntimeError, 'Rejected by service'):
            self.invoke([rejected])
        record, = self.records()
        self.assertEqual(record['rejection_reason'], 'response_failed')
        self.assertFalse(record['accepted'])
        self.assertEqual(self.slots.call_count, 1)

    def test_transient_errors_preserve_request_and_wait_before_each_retry(self):
        request = httpx.Request('POST', 'https://example.invalid/v1/responses')
        unavailable = APIStatusError('unavailable', response=httpx.Response(
            522, request=request, headers={'retry-after': '120'}), body={'retry_after': 90})
        timeout = APITimeoutError(request=request)
        answer, _ = self.invoke([unavailable, timeout, response()])
        self.assertEqual(answer, 'accepted')
        self.assertEqual([call.args[0] for call in self.sleep.call_args_list], [120, 20])
        calls = self.client.responses.create.call_args_list
        self.assertTrue(all(c == calls[0] for c in calls))
        self.assertEqual(self.slots.call_count, 3)
        self.assertEqual([r['will_retry'] for r in self.records('request-errors.jsonl')], [True, True])

    def test_budgets_are_independent_and_bounded_across_interleaved_errors(self):
        error = APITimeoutError(request=httpx.Request('POST', 'https://example.invalid'))
        with patch.dict(os.environ, {'AUTOCONTROL_ARENA_TRANSIENT_RETRIES': '2',
                                     'AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES': '1'}):
            with self.assertRaises(APITimeoutError):
                self.invoke([error, response('gpt-6-sol'), error, error, response()])
        self.assertEqual(self.slots.call_count, 4)
        self.assertEqual([r['will_retry'] for r in self.records('request-errors.jsonl')], [True, True, False])
        self.assertEqual(self.sleep.call_count, 2)

    def test_transient_failures_do_not_spend_model_retry_budget(self):
        error = APITimeoutError(request=httpx.Request('POST', 'https://example.invalid'))
        with patch.dict(os.environ, {'AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES': '1'}):
            self.invoke([error, response('gpt-6-sol'), error, response()])
        self.assertEqual(self.slots.call_count, 4)

    def test_stream_failures_discard_partial_output_and_retry(self):
        def broken():
            yield SimpleNamespace(type='response.output_text.delta', delta='discard this')
            raise httpx.RemoteProtocolError('connection interrupted')
        answer, usage = self.invoke([nullcontext(broken()), nullcontext([]), response()])
        self.assertEqual(answer, 'accepted')
        self.assertEqual(usage['total_tokens'], 12)
        self.assertEqual(self.records()[0]['attempt'], 3)
        self.assertEqual(self.slots.call_count, 3)

    def test_failed_response_with_transient_code_is_recorded_then_retried(self):
        rejected = response(failed=True)
        self.invoke([rejected, response()])
        self.assertEqual([r['accepted'] for r in self.records()], [False, True])
        self.assertEqual(self.sleep.call_count, 1)

    def test_policy_takes_precedence_over_wrong_model_and_server_status(self):
        rejected = response(model='gpt-6-sol', failed=True)
        rejected.error = ResponseError.model_construct(code='cyber_policy', message='policy rejected')
        with self.assertRaisesRegex(RuntimeError, 'policy rejected'):
            self.invoke([rejected])
        self.assertEqual(self.records()[0]['rejection_reason'], 'response_failed')
        self.assertEqual(self.records('request-errors.jsonl')[0]['code'], 'cyber_policy')
        self.sleep.assert_not_called()
        request = httpx.Request('POST', 'https://example.invalid')
        error = APIStatusError('policy', response=httpx.Response(500, request=request),
                               body={'error': {'code': 'bio_policy'}})
        with self.assertRaises(APIStatusError):
            self.invoke([error])
        self.sleep.assert_not_called()

    def test_http_429_retries_but_authentication_and_context_errors_do_not(self):
        request = httpx.Request('POST', 'https://example.invalid')
        error = APIStatusError('rate limited', response=httpx.Response(429, request=request), body={})
        self.invoke([error, response()])
        self.assertEqual(self.sleep.call_count, 1)
        self.sleep.reset_mock()
        for status, code in [(401, 'invalid_api_key'), (403, None), (400, 'context_length_exceeded')]:
            with self.subTest(status=status):
                error = APIStatusError('permanent', response=httpx.Response(status, request=request),
                                       body={'error': {'code': code}})
                with self.assertRaises(APIStatusError):
                    self.invoke([error])
        self.sleep.assert_not_called()

    def test_generic_sse_500_is_not_blindly_retried_and_body_is_saved(self):
        body = {'message': 'Response API in-stream error', 'code': '500'}
        error = APIError('stream error', request=httpx.Request('POST', 'https://example.invalid'), body=body)
        with self.assertRaises(APIError):
            self.invoke([error])
        self.sleep.assert_not_called()
        self.assertEqual(self.records('request-errors.jsonl')[0]['body'], body)

    def test_structured_sse_rate_limit_is_retried(self):
        error = APIError('rate limit', request=httpx.Request('POST', 'https://example.invalid'),
                         body={'code': 'rate_limit_exceeded'})
        self.invoke([error, response()])
        self.assertEqual(self.sleep.call_count, 1)

    def test_retry_after_date_milliseconds_and_backoff_cap(self):
        request = httpx.Request('POST', 'https://example.invalid')
        error = APIStatusError('unavailable', response=httpx.Response(503, request=request,
            headers={'retry-after': 'Thu, 01 Jan 1970 00:02:00 GMT'}), body={})
        with patch('local.responses_provider.time.time', return_value=0):
            self.assertEqual(retry_delay(error, 1), 120)
        error.response.headers = httpx.Headers({'retry-after-ms': '15000'})
        self.assertEqual(retry_delay(error, 1), 15)
        error.response.headers = httpx.Headers()
        self.assertEqual([retry_delay(error, i) for i in range(1, 9)],
                         [10, 20, 40, 80, 160, 300, 300, 300])

    def test_real_sdk_stream_error_and_http_failure_then_success(self):
        requests = []
        def transport(request):
            requests.append(request.content)
            if len(requests) == 1:
                return httpx.Response(522, json={'error': {'message': 'upstream unavailable'}},
                                      headers={'Retry-After': '120'})
            if len(requests) == 2:
                data = {'error': {'code': 'rate_limit_exceeded', 'message': 'busy'}}
            else:
                data = {'type': 'response.completed', 'response': response().model_dump()}
            return httpx.Response(200, headers={'Content-Type': 'text/event-stream'},
                                  text='data: ' + json.dumps(data) + '\n\ndata: [DONE]\n\n')
        client = OpenAI(api_key='test', base_url='https://example.invalid', max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(transport)))
        with patch('local.responses_provider.OpenAI', return_value=client):
            answer, _ = self.invoke([])
        self.assertEqual(answer, 'accepted')
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(r == requests[0] for r in requests))
        self.assertEqual([r['status_code'] for r in self.records('request-errors.jsonl')], [522, None])
        self.assertEqual([r['retry_delay_seconds'] for r in self.records('request-errors.jsonl')], [120, 20])

    def test_sdk_policy_error_is_persisted_as_future_retry_exclusion(self):
        from local.rerun import run_item
        root = Path(self.directory.name)
        item = {'id': 'sample', 'user_intent': 'test', 'environment': 'env',
                'stress_level': 1, 'temptation_level': 1, 'env_complexity_level': 1}
        manifest = {'root': str(root), 'max_steps': 200, 'timeout_seconds': 10,
                    'profile': 'test', 'retire_error_codes': ['cyber_policy']}
        test = self
        class Process:
            pid = 123
            def __init__(self, *args, **kwargs):
                error = APIError('policy', request=httpx.Request('POST', 'https://example.invalid'),
                                 body={'code': 'cyber_policy', 'message': 'rejected'})
                with patch.dict(os.environ, kwargs['env']):
                    with test.assertRaises(APIError):
                        test.invoke([error])
            def wait(self, **kwargs):
                return 0
        with patch('local.rerun.subprocess.Popen', Process):
            result = run_item(item, manifest, root)
        self.assertTrue(result['exclude_from_future_retries'])
        self.assertEqual(result['retry_exclusion_codes'], ['cyber_policy'])
        saved = json.loads((root / 'items/sample/status.json').read_text())
        self.assertEqual(saved, result)


if __name__ == '__main__':
    unittest.main()
