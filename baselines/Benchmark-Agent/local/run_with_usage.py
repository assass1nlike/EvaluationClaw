"""Run the official CLI with observational token accounting."""

import json
import hashlib
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from uuid import uuid4


TOKEN_FIELDS = ("prompt_tokens", "completion_tokens", "total_tokens")


class UsageRecorder:
    def __init__(self, output_dir):
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:8]
        self.directory = Path(output_dir) / "token_usage" / run_id
        self.lock = threading.Lock()
        self.summary = {
            "run_id": run_id,
            "status": "running",
            "finished_calls": 0,
            "failed_calls": 0,
            "calls_with_incomplete_usage": 0,
            "logging_errors": 0,
            "reported_tokens": dict.fromkeys(TOKEN_FIELDS, 0),
            "by_model": {},
        }
        self._save_safely()

    def _save_summary(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / "summary.json.tmp"
        temporary.write_text(json.dumps(self.summary, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.directory / "summary.json")

    def _logging_error(self, exc):
        self.summary["logging_errors"] += 1
        # Do not print request data or exception text, which may contain secrets.
        try:
            print(f"[token usage] Recording failed ({type(exc).__name__}); totals may be incomplete.", file=sys.stderr)
        except Exception:
            pass

    def _save_safely(self):
        try:
            self._save_summary()
        except Exception as exc:
            self._logging_error(exc)

    def record(self, source, model, response=None, error=None, api_key=None, request_settings=None):
        with self.lock:
            try:
                usage = getattr(response, "usage", None)
                if hasattr(usage, "model_dump"):
                    usage = usage.model_dump()
                if not isinstance(usage, dict):
                    usage = None
                # Keep original provider usage; normalize only the aggregate field names.
                normalized = dict(usage or {})
                if "prompt_tokens" not in normalized and "input_tokens" in normalized:
                    normalized["prompt_tokens"] = normalized["input_tokens"]
                if "completion_tokens" not in normalized and "output_tokens" in normalized:
                    normalized["completion_tokens"] = normalized["output_tokens"]
                counts = {
                    key: value for key in TOKEN_FIELDS
                    if type(value := normalized.get(key)) is int and value >= 0
                }
                event = {
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                    "source": source,
                    "requested_model": model,
                    "response_model": getattr(response, "model", None),
                    "response_id": getattr(response, "id", None),
                    "error_type": type(error).__name__ if error is not None else None,
                    "usage": usage,
                }
                if request_settings is not None:
                    event["request_settings"] = request_settings
                if source.endswith("request_response"):
                    event["credential_id"] = hashlib.sha256(api_key.encode()).hexdigest()[:12] if api_key else None
                    http_response = getattr(error, "response", None)
                    event["http_status"] = getattr(error, "status_code", 200 if response is not None else None)
                    event["error_code"] = getattr(error, "code", None)
                    event["request_id"] = getattr(error, "request_id", None) or getattr(response, "_request_id", None)
                    event["rate_limit_headers"] = {
                        k: v for k, v in (http_response.headers.items() if http_response is not None else [])
                        if k.lower().startswith(("retry-after", "x-ratelimit-", "x-ms-ratelimit-", "x-ms-retry-after"))
                    }
                if getattr(response, "object", None) == "response":
                    event["response_status"] = response.status
                    event["incomplete_details"] = (
                        response.incomplete_details.model_dump() if response.incomplete_details else None
                    )
                    event["web_search_calls"] = [item.model_dump() for item in response.output
                                                 if item.type == "web_search_call"]
                    event["tool_usage"] = getattr(response, "tool_usage", None)
                self.summary["finished_calls"] += 1
                self.summary["failed_calls"] += int(error is not None)
                self.summary["calls_with_incomplete_usage"] += int(len(counts) != len(TOKEN_FIELDS))
                model_totals = self.summary["by_model"].setdefault(
                    str(model), {"finished_calls": 0, **dict.fromkeys(TOKEN_FIELDS, 0)}
                )
                model_totals["finished_calls"] += 1
                for key, value in counts.items():
                    self.summary["reported_tokens"][key] += value
                    model_totals[key] += value
                self.directory.mkdir(parents=True, exist_ok=True)
                with (self.directory / "calls.jsonl").open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
                self._save_summary()
            except Exception as exc:
                self._logging_error(exc)

    def finish(self, status):
        with self.lock:
            self.summary["status"] = status
            self._save_safely()


def request_settings(kwargs):
    fields = ("thinking", "enable_thinking", "reasoning_effort", "reasoning", "tool_choice", "max_tokens", "max_output_tokens")
    body = {**kwargs, **(kwargs.get("extra_body") or {})}
    return {name: body[name] for name in fields if name in body}


def observe_sync(call, recorder, source):
    @wraps(call)
    def wrapped(*args, **kwargs):
        try:
            response = call(*args, **kwargs)
        except BaseException as exc:
            recorder.record(source, kwargs.get("model"), error=exc, api_key=kwargs.get("api_key"), request_settings=request_settings(kwargs))
            raise
        recorder.record(source, kwargs.get("model"), response=response, api_key=kwargs.get("api_key"), request_settings=request_settings(kwargs))
        return response
    return wrapped


def observe_async(call, recorder, source):
    @wraps(call)
    async def wrapped(*args, **kwargs):
        try:
            response = await call(*args, **kwargs)
        except BaseException as exc:
            recorder.record(source, kwargs.get("model"), error=exc, request_settings=request_settings(kwargs))
            raise
        recorder.record(source, kwargs.get("model"), response=response, request_settings=request_settings(kwargs))
        return response
    return wrapped


@contextmanager
def observe_calls(recorder):
    from utils import core, llm_caller, native_responses

    targets = (
        (core, "completion", observe_sync),
        (core, "acompletion", observe_async),
        (llm_caller, "completion", observe_sync),
        (native_responses, "request_response", observe_sync),
    )
    originals = []
    try:
        for module, name, wrap in targets:
            original = getattr(module, name)
            originals.append((module, name, original))
            setattr(module, name, wrap(original, recorder, f"{module.__name__}.{name}"))
        yield
    finally:
        for module, name, original in originals:
            setattr(module, name, original)


def main():
    # Match imports when running generate_benchmark.py directly from the repository.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import generate_benchmark
    from local.model_runtime import configured_calls, seed_everything

    args = generate_benchmark.get_args()
    seed_everything(42)
    recorder = UsageRecorder(args.cache_path + args.topic_id)
    status = "failed"
    try:
        with observe_calls(recorder), configured_calls():
            generate_benchmark.main(args)
        status = "completed"
    finally:
        recorder.finish(status)
        print(f"[token usage] {recorder.directory / 'summary.json'}")


if __name__ == "__main__":
    main()
