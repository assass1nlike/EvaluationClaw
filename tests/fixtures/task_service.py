"""Deterministic task service exercising the public JSON-lines interface."""
import json
import sys
from pathlib import Path

counter = 0
for line in sys.stdin:
    request = json.loads(line)
    method, params = request["method"], request["params"]
    if method == "describe":
        result = {"version": "1", "methods": ["initialize", "call_tool", "checkpoint", "restore", "finalize", "score", "inspect"]}
    elif method == "initialize":
        counter = params.get("initial_state") or 0
        result = {"state": counter, "tools": [{"name": "increment", "parameters": {
            "type": "object", "properties": {}, "additionalProperties": False}}]}
    elif method == "call_tool":
        counter += 1
        result = {"content": str(counter)}
    elif method == "checkpoint":
        result = {"counter": counter}
    elif method == "restore":
        counter = params["checkpoint"]["counter"]
        result = {}
    elif method == "finalize":
        Path("result.txt").write_text(str(counter))
        result = {"state": counter, "artifacts": {"exported": True}, "artifact_files": {"result.txt": "/component/result.txt"}}
    elif method == "score":
        assert params["episode"]["artifacts"]["exported"]
        assert int(Path("/component/outputs/result.txt").read_text()) == params["episode"]["final_state"]
        result = {"metrics": [{"metric": "utility", "value": params["episode"]["final_state"]},
                              {"metric": "attack_success", "value": 0}]}
    elif method == "inspect":
        result = {"state": counter}
    else:
        raise ValueError(method)
    print(json.dumps({"id": request["id"], "result": result}), flush=True)
