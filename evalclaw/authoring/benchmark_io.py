"""Dependency-free JSON-lines transport for benchmark programs."""
import itertools
import json
import sys
import threading

_lock = threading.Lock()
_ids = itertools.count(1)


def _send(value):
    line = json.dumps(value, ensure_ascii=False, allow_nan=False)
    with _lock:
        print(line, flush=True)


def event(kind, data):
    """Publish an observation; the runner records its source and receipt time."""
    _send({"event": {"kind": kind, "data": data}})


def model(role, messages):
    """Request a runtime-bound auxiliary model from within a method handler."""
    call_id = f"model-{next(_ids)}"
    _send({"id": call_id, "model_request": {"role": role, "messages": messages}})
    line = sys.stdin.readline()
    if not line:
        raise EOFError("Runner disconnected during model callback")
    response = json.loads(line)
    if response.get("id") != call_id or "model_result" not in response:
        raise RuntimeError("Unexpected model callback response")
    return response["model_result"]


def serve(methods, version="1"):
    """Call handler(params, config); report exceptions as execution errors, not scores."""
    for line in sys.stdin:
        request = json.loads(line)
        try:
            if request["method"] == "describe":
                result = {"version": version, "methods": sorted(methods)}
            else:
                result = methods[request["method"]](request.get("params", {}), request.get("config", {}))
            _send({"id": request["id"], "result": result})
        except Exception as exc:
            _send({"id": request["id"], "error": f"{type(exc).__name__}: {exc}"})
