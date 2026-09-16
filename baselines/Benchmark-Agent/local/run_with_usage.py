"""Run the official CLI with observational token accounting."""

import json
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

    def record(self, source, model, response=None, error=None):
        with self.lock:
            try:
                usage = getattr(response, "usage", None)
                if hasattr(usage, "model_dump"):
                    usage = usage.model_dump()
                if not isinstance(usage, dict):
                    usage = None
                counts = {
                    key: value for key in TOKEN_FIELDS
                    if type(value := (usage or {}).get(key)) is int and value >= 0
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


def observe_sync(call, recorder, source):
    @wraps(call)
    def wrapped(*args, **kwargs):
        try:
            response = call(*args, **kwargs)
        except BaseException as exc:
            recorder.record(source, kwargs.get("model"), error=exc)
            raise
        recorder.record(source, kwargs.get("model"), response=response)
        return response
    return wrapped


def observe_async(call, recorder, source):
    @wraps(call)
    async def wrapped(*args, **kwargs):
        try:
            response = await call(*args, **kwargs)
        except BaseException as exc:
            recorder.record(source, kwargs.get("model"), error=exc)
            raise
        recorder.record(source, kwargs.get("model"), response=response)
        return response
    return wrapped


@contextmanager
def observe_calls(recorder):
    from utils import core, llm_caller

    targets = (
        (core, "completion", observe_sync),
        (core, "acompletion", observe_async),
        (llm_caller, "completion", observe_sync),
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

    args = generate_benchmark.get_args()
    recorder = UsageRecorder(args.cache_path + args.topic_id)
    status = "failed"
    try:
        with observe_calls(recorder):
            generate_benchmark.main(args)
        status = "completed"
    finally:
        recorder.finish(status)
        print(f"[token usage] {recorder.directory / 'summary.json'}")


if __name__ == "__main__":
    main()
