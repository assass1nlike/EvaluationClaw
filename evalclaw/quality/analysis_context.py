"""Bounded analysis views backed by complete, paginated evidence snapshots."""
from __future__ import annotations

import json
from pathlib import Path

from ..diagnostics import write_json
from ..execution.judge_evidence import evidence_page
from ..protocols.tool import ToolResult, ToolSpec


CONTEXT_TOOL = ToolSpec(
    name="read_analysis_context",
    description="Read complete analysis input or archived conversation evidence. Use source and JSON pointer from an excerpt; paginate until the needed evidence is read.",
    parameters={"type": "object", "properties": {
        "source": {"type": "string"}, "pointer": {"type": "string", "default": ""},
        "offset": {"type": "integer", "minimum": 0},
        "max_chars": {"type": "integer", "minimum": 100, "maximum": 20000},
    }, "required": ["source"], "additionalProperties": False},
)

CONTEXT_INSTRUCTIONS = """Analysis input and tool replies may be bounded views. Excerpts
are not complete evidence and omitted content is not evidence of absence. Read
read_analysis_context(source, pointer, offset, max_chars) to recover any omitted
input or archived conversation exactly. All items and completed iterations remain
available, including passing results. Inspect relevant complete evidence before
assigning a failure or excluding an item. If a collection is paginated, inspect
its remaining entries before claiming exhaustive coverage.
When earlier conversation is archived, resume its investigation: retain the
hypotheses, exclusions, unresolved questions and evidence already established.
Use the archive to recover details rather than guessing or restarting the work.
"""


def text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def size(value):
    return len(text(value).encode("utf-8"))


def bounded_view(value, source, budget, pointer=""):
    """Keep identities/scalars and distribute detail space across the collection."""
    length = size(value)
    if length <= budget:
        return value
    ref = {"source": source, "pointer": pointer, "bytes": length}
    if isinstance(value, str):
        # UTF-8 can use four bytes per character; also leave room for JSON escaping.
        count = max(0, min(4000, (budget - size(ref) - 64) // 12))
        if count:
            ref["excerpt"] = value[:count] + "\n[excerpt; read complete source]\n" + value[-count:]
    elif isinstance(value, dict):
        identity = {k: v for k, v in value.items() if k in {
            "id", "item_id", "target_id", "iteration", "dimension_id", "task_type",
            "challenge_effort", "score", "status", "remaining_probe_iterations", "max_probe_tasks",
        } and size(v) < 256}
        rest = [k for k in value if k not in identity]
        available = budget - size(ref) - size(identity) - 128
        lengths = {k: size(value[k]) for k in rest}
        total = max(1, sum(lengths.values()))
        if available >= 256:
            ref["view"] = {**identity, **{
                k: bounded_view(value[k], source, max(128, available * lengths[k] // total), pointer + "/" + k.replace("~", "~0").replace("/", "~1"))
                for k in rest}}
        else:
            ref["view"] = identity
            ref["keys"] = list(value)[:20]
    elif isinstance(value, list):
        ref["count"] = len(value)
        allowance = (budget - size(ref) - 64) // max(1, len(value))
        if allowance >= 256:
            ref["entries"] = [bounded_view(v, source, allowance, pointer + f"/{i}") for i, v in enumerate(value)]
        else:
            ref["note"] = "Read this collection in pages; entries are not all shown."
    if size(ref) > budget:
        ref = {"source": source, "pointer": pointer, "bytes": length}
        if isinstance(value, list):
            ref["count"] = len(value)
    return ref


class AnalysisContext:
    def __init__(self, payload, directory: Path, model: str):
        self.directory = directory
        self.sources = {}
        # A byte bound is deliberately conservative, not an estimated token count.
        # DeepSeek's 1M window also accommodates its 393K output reservation.
        self.budget = 384_000 if model.split("/")[-1].lower() in {
            "deepseek-flash", "deepseek-v4-flash", "deepseek-v4-pro",
        } else 96_000
        self.save("request", payload)
        catalog = []
        scopes = [(0, payload.get("benchmark", {}).get("tasks", payload.get("tasks", [])),
                   payload.get("main_run", {}).get("results", []), "/benchmark/tasks" if "benchmark" in payload else "/tasks", "/main_run/results")]
        scopes.extend((entry.get("iteration"), entry.get("tasks", []), entry.get("run", {}).get("results", []),
                       f"/verification_history/{i}/tasks", f"/verification_history/{i}/run/results")
                      for i, entry in enumerate(payload.get("verification_history", [])))
        for iteration, tasks, results, task_path, result_path in scopes:
            indices = {task["id"]: i for i, task in enumerate(tasks)}
            seen = set()
            for i, result in enumerate(results):
                item_id = result["item_id"]
                row = {"iteration": iteration, "item_id": item_id, "target_id": result["target_id"],
                       "score": result["score"], "execution_error": bool(result.get("error")),
                       "result": f"{result_path}/{i}"}
                if item_id in indices:
                    row["task"] = f"{task_path}/{indices[item_id]}"
                catalog.append(row)
                seen.add(item_id)
            for item_id, i in indices.items():
                if item_id not in seen:
                    catalog.append({"iteration": iteration, "item_id": item_id, "task": f"{task_path}/{i}"})
        assessments = {}
        for i, entry in enumerate(payload.get("verification_history", [])):
            for j, assessment in enumerate(entry.get("evidence_assessments", [])):
                key = (assessment.get("iteration"), assessment.get("item_id"), assessment.get("target_id"))
                assessments[key] = (assessment.get("status"), f"/verification_history/{i}/evidence_assessments/{j}")
        for row in catalog:
            assessment = assessments.get((row["iteration"], row["item_id"], row.get("target_id")))
            if assessment:
                row["assessment_status"], row["assessment"] = assessment
        self.save("item-index", catalog)
        self.initial = self.message()

    def save(self, name, value):
        self.sources[name] = value
        write_json(self.directory / f"{name}.json", value)

    def message(self, history=None):
        if history is None and size(self.sources["request"]) <= self.budget * 2 // 3:
            return {"role": "user", "content": text(self.sources["request"])}
        payload = {
            "controls": {k: self.sources["request"][k] for k in ("remaining_probe_iterations", "max_probe_tasks")
                         if k in self.sources["request"]},
            "analysis_request": bounded_view(self.sources["request"], "request", self.budget // 3),
            "item_index": bounded_view(self.sources["item-index"], "item-index", self.budget // 3),
            "index_note": "task/result are JSON pointers into source=request; every evaluated item is indexed, including passing items.",
        }
        if history is not None:
            payload["conversation_archive"] = bounded_view(self.sources[history], history, self.budget // 4)
        return {"role": "user", "content": text(payload)}

    def fit(self, messages, *, force=False):
        if not force and size(messages) <= self.budget:
            return messages
        # Restart at a user-message boundary. Do not orphan native tool calls,
        # encrypted reasoning blocks, or Responses API message references.
        history = f"history-{len(self.sources):04d}"
        self.save(history, list(messages))
        return [self.message(history)]

    def bound_result(self, result):
        if len(result.content.encode("utf-8")) <= self.budget // 8:
            return result
        source = f"tool-{len(self.sources):04d}"
        self.save(source, result.content)
        return result.model_copy(update={"content": text(bounded_view(
            result.content, source, self.budget // 8))})

    def read(self, call):
        args = call.arguments
        try:
            source = args["source"]
            offset = max(0, int(args.get("offset", 0)))
            limit = max(100, min(int(args.get("max_chars", 12000)), 20000, self.budget // 24))
            page = evidence_page(self.sources[source], args.get("pointer", ""), offset, limit)
            return ToolResult(tool_call_id=call.id, name=call.name, content=text({
                "source": source, "pointer": args.get("pointer", ""), "offset": offset, **page}))
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            return ToolResult(tool_call_id=call.id, name=call.name, error="invalid_context_path", content=str(exc))
