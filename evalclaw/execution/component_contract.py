"""Wire checks shared by runtime components and author conformance tests."""
import math

import jsonschema

from ..protocols.task_definition import MetricResult, TaskMessage
from ..protocols.tool import ToolResult, ToolSpec


def scoring_payload(task, scorer, episode):
    """Build the same scoring evidence for execution and author interface tests."""
    from ..protocols.submission import submission_contract

    evidence = episode.model_dump(mode="json")
    evidence["metrics"] = [m for m in evidence["metrics"] if m["metric"] in scorer.depends_on]
    evidence["events"] = [e for e in evidence["events"] if e["origin"] != "judge"]
    if episode.bindings.get("purpose") == "scripted_trial":
        for event in evidence["events"]:
            if event["origin"] == "trial_target":
                event["origin"] = "target"
    references = {r.id: r for r in task.evaluation.references}
    payload = {"task": task.model_dump(mode="json"), "episode": evidence,
               "references": [references[r].model_dump(mode="json") for r in scorer.references]}
    contract = submission_contract(task)
    if contract:
        payload["submission_contract"] = contract
    return payload


def validate_component_result(method, result):
    # Checkpoints and inspection deliberately permit arbitrary JSON values.
    if method not in {"describe", "initialize", "call_tool", "finalize", "score", "next"}:
        return
    jsonschema.validate(result, {"type": "object"})
    if method == "describe":
        jsonschema.validate(result, {"type": "object", "required": ["version", "methods"],
            "properties": {"version": {"type": "string"},
                           "methods": {"type": "array", "items": {"type": "string"}}}})
    if method in {"initialize", "call_tool"}:
        if "error" in result:
            jsonschema.validate(result["error"], ToolResult.model_json_schema()["properties"]["error"])
        jsonschema.validate(result.get("messages", []), {"type": "array"})
        for message in result.get("messages", []):
            parsed = TaskMessage.model_validate(message)
            if method == "call_tool" and parsed.role != "user":
                raise ValueError("Environment observations must be user messages")
    if method == "initialize":
        jsonschema.validate(result.get("tools", []), {"type": "array"})
        for tool in result.get("tools", []):
            spec = ToolSpec.model_validate(tool)
            jsonschema.Draft202012Validator.check_schema(spec.parameters)
    if method == "finalize" and "artifact_files" in result:
        jsonschema.validate(result["artifact_files"], {"type": "object", "additionalProperties": {"type": "string"}})
    if method == "score":
        jsonschema.validate(result, {"type": "object", "required": ["metrics"],
            "properties": {"metrics": {"type": "array", "items": MetricResult.model_json_schema()}}})
    if method == "next":
        jsonschema.validate(result, {"type": "object", "required": ["actions"], "properties": {
            "actions": {"type": "array", "minItems": 1, "items": {"type": "object",
                "required": ["action"], "properties": {"action": {"type": "string"}}}}}})


def validate_metrics(scorer, raw, definitions):
    validate_component_result("score", raw)
    results = [MetricResult.model_validate(r) for r in raw["metrics"]]
    if sorted(r.metric for r in results) != sorted(scorer.metrics):
        raise ValueError(f"Scorer must return exactly these metrics: {scorer.metrics}")
    definitions = {m.id: m for m in definitions}
    for result in results:
        if result.status != "valid":
            continue
        metric = definitions[result.metric]
        jsonschema.validate(result.value, {"type": metric.value_type})
        if isinstance(result.value, (int, float)) and not isinstance(result.value, bool):
            if not math.isfinite(result.value):
                raise ValueError("Metric value is not finite")
            original = result.value
            for bound, outside in ((metric.minimum, metric.minimum is not None and original < metric.minimum),
                                   (metric.maximum, metric.maximum is not None and original > metric.maximum)):
                if not outside:
                    continue
                # At most four representable steps at the declared boundary.
                # No absolute epsilon: near zero, only subnormal roundoff qualifies.
                if not isinstance(original, float) or abs(original - bound) > 4 * math.ulp(bound):
                    raise ValueError(f"Metric {metric.id} outside [{metric.minimum}, {metric.maximum}]")
                result.value = bound
                result.raw = {"reported_metric": next(r for r in raw["metrics"] if r["metric"] == result.metric),
                              "normalization": "floating_point_boundary"}
    return results
