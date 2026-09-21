"""Responses transport for the local high-effort GPT evaluation."""

import hashlib
import json
import os
from pathlib import Path
import time
import uuid
from email.utils import parsedate_to_datetime

import httpx
from openai import APIConnectionError, APIError, OpenAI

from src.infra.llm.provider_registry import get_provider_registry


MODEL_MISMATCH_RETRIES = 5
TRANSIENT_RETRIES = 8
TRANSIENT_CODES = {
    'rate_limit_exceeded', 'gateway_concurrency_limit', 'server_error',
    'internal_server_error', 'model_service_unavailable', 'service_unavailable',
    'overloaded', 'incomplete_stream',
}
PERMANENT_CODES = {'cyber_policy', 'bio_policy', 'content_filter', 'invalid_prompt',
                   'context_length_exceeded', 'invalid_api_key', 'insufficient_quota'}


class RequestFailure(RuntimeError):
    def __init__(self, body):
        super().__init__(str(body))
        self.body = body


def error_details(error):
    body = getattr(error, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else {}
    code = detail.get('code') if isinstance(detail, dict) else None
    status = getattr(error, 'status_code', None)
    if code in PERMANENT_CODES:
        retryable = False
    else:
        retryable = (isinstance(error, (APIConnectionError, httpx.TransportError))
                     or code in TRANSIENT_CODES or status in (408, 429)
                     or isinstance(status, int) and 500 <= status < 600)
    # A generic SSE code=500 can hide policy errors; only explicit transient codes qualify.
    return {'error_type': type(error).__name__, 'message': str(error),
            'status_code': status, 'code': code, 'body': body, 'retryable': retryable}


def retry_delay(error, retry_number):
    delay = min(10 * 2 ** (retry_number - 1), 300)
    response = getattr(error, 'response', None)
    headers = response.headers if response is not None else {}
    for name, scale in [('retry-after-ms', 0.001), ('retry-after', 1)]:
        value = headers.get(name)
        if value is not None:
            try:
                delay = max(delay, float(value) * scale)
            except ValueError:
                if name == 'retry-after':
                    try:
                        delay = max(delay, parsedate_to_datetime(value).timestamp() - time.time())
                    except (ValueError, TypeError, OverflowError):
                        pass
    body = getattr(error, 'body', None)
    if isinstance(body, dict):
        for detail in (body, body.get('error')):
            if isinstance(detail, dict) and isinstance(detail.get('retry_after'), (int, float)):
                delay = max(delay, detail['retry_after'])
    return delay


def record_error(record):
    output = os.environ.get('AUTOCONTROL_ARENA_RESULTS_DIR')
    if output:
        with (Path(output) / 'request-errors.jsonl').open('a') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')


def record_response(response, request, request_id, attempt, rejection, started_at):
    output = os.environ.get('AUTOCONTROL_ARENA_RESULTS_DIR')
    if not output:
        return
    summaries = [part.text for item in response.output or [] if item.type == 'reasoning'
                 for part in item.summary or []]
    record = {
        'request_id': request_id, 'attempt': attempt, 'request_started_at': started_at,
        'response_id': response.id, 'requested_model': request['model'],
        'model': response.model, 'status': response.status,
        'accepted': rejection is None, 'rejection_reason': rejection,
        'requested_reasoning': request['reasoning'],
        'returned_reasoning': response.reasoning.model_dump() if response.reasoning else None,
        'requested_max_output_tokens': request['max_output_tokens'],
        'returned_max_output_tokens': response.max_output_tokens,
        'requested_temperature': request.get('temperature'), 'returned_temperature': response.temperature,
        'system_instructions_preserved': response.instructions == request['instructions'],
        'system_sha256': hashlib.sha256(request['instructions'].encode()).hexdigest(),
        'returned_system_sha256': hashlib.sha256(response.instructions.encode()).hexdigest()
            if isinstance(response.instructions, str) else None,
        'input_message_count': len(request['input']),
        'usage': response.usage.model_dump() if response.usage else None,
        'reasoning_summary_count': len(summaries),
    }
    with (Path(output) / 'responses-usage.jsonl').open('a') as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    if rejection:
        with (Path(output) / 'rejected-responses.jsonl').open('a') as handle:
            handle.write(json.dumps({
                'request_id': request_id, 'attempt': attempt, 'rejection_reason': rejection,
                'requested_model': request['model'], 'requested_instructions': request['instructions'],
                'response': response.model_dump(),
            }, ensure_ascii=False) + '\n')


def invoke_responses(messages, llm_config, temperature=None, max_tokens=None,
                     timeout=None, return_usage=False, api_type=None,
                     extract_answer_only=True):
    instructions = '\n\n'.join(m['content'] for m in messages if m['role'] == 'system')
    inputs = [m for m in messages if m['role'] != 'system']
    request = dict(
        model=llm_config['model_name'], instructions=instructions, input=inputs,
        reasoning={'effort': 'high', 'summary': 'auto'},
        max_output_tokens=max_tokens, temperature=temperature,
        store=False, stream=True,
    )
    if os.environ.get('AUTOCONTROL_ARENA_OMIT_TEMPERATURE') == '1':
        request.pop('temperature')
    request_id = uuid.uuid4().hex
    model_retries = int(os.environ.get('AUTOCONTROL_ARENA_MODEL_MISMATCH_RETRIES', MODEL_MISMATCH_RETRIES))
    transient_retries = int(os.environ.get('AUTOCONTROL_ARENA_TRANSIENT_RETRIES', TRANSIENT_RETRIES))
    if min(model_retries, transient_retries) < 0:
        raise ValueError('Retry limits must be nonnegative')
    attempt = model_failures = transient_failures = 0
    with OpenAI(api_key=llm_config['api_key'], base_url=llm_config['api_base_url'],
                timeout=timeout, max_retries=0) as client:
        while True:
            attempt += 1
            response = None
            if os.environ.get('AUTOCONTROL_ARENA_TARGET_RPM'):
                from local.request_rate import wait_for_slot

                wait_for_slot(os.environ['AUTOCONTROL_ARENA_TARGET_RATE_LIMIT_FILE'],
                              float(os.environ['AUTOCONTROL_ARENA_TARGET_RPM']))
            started_at = time.time()
            try:
                with client.responses.create(**request) as stream:
                    for event in stream:
                        if event.type in ('response.completed', 'response.incomplete', 'response.failed'):
                            response = event.response
                        elif event.type == 'error':
                            raise RequestFailure(event.model_dump())
                if response is None:
                    raise RequestFailure({'code': 'incomplete_stream',
                                          'message': 'Responses stream ended without a final response'})
                if response.status == 'failed':
                    record_response(response, request, request_id, attempt, 'response_failed', started_at)
                    raise RequestFailure(response.error.model_dump() if response.error else {})
            except (APIError, httpx.TransportError, RequestFailure) as error:
                details = error_details(error)
                will_retry = details['retryable'] and transient_failures < transient_retries
                delay = retry_delay(error, transient_failures + 1) if will_retry else 0
                record_error(dict(details, request_id=request_id, attempt=attempt,
                                  request_started_at=started_at, will_retry=will_retry,
                                  retry_delay_seconds=delay))
                if not will_retry:
                    raise
                transient_failures += 1
                time.sleep(delay)
                continue
            if response.model != request['model']:
                rejection = 'model_mismatch'
            elif response.instructions != instructions:
                rejection = 'instructions_mismatch'
            elif response.reasoning is None or response.reasoning.effort != 'high':
                rejection = 'reasoning_effort_mismatch'
            else:
                rejection = None
            record_response(response, request, request_id, attempt, rejection, started_at)
            if rejection == 'model_mismatch':
                model_failures += 1
                if model_failures <= model_retries:
                    continue
                raise RuntimeError(f'Expected {request["model"]}, received {response.model}; model retries exhausted')
            if rejection == 'instructions_mismatch':
                raise RuntimeError('Gateway did not preserve the requested system instructions; see rejected-responses.jsonl')
            if rejection == 'reasoning_effort_mismatch':
                raise RuntimeError('Gateway did not confirm reasoning effort high')
            break

    raw_usage = response.usage
    usage = {
        'prompt_tokens': raw_usage.input_tokens,
        'completion_tokens': raw_usage.output_tokens,
        'total_tokens': raw_usage.total_tokens,
        'reasoning_tokens': raw_usage.output_tokens_details.reasoning_tokens or 0,
        'cached_tokens': raw_usage.input_tokens_details.cached_tokens or 0,
    }
    summaries = [part.text for item in response.output or [] if item.type == 'reasoning'
                 for part in item.summary or []]
    payload = response.output_text if extract_answer_only else {
        'choices': [{'message': {'content': response.output_text,
                                'reasoning_content': '\n'.join(summaries) or None}}]
    }
    return (payload, usage) if return_usage else payload


def register():
    get_provider_registry().register('local_responses_high', invoke_responses)
