import json

from evalclaw.models.llm import TargetToolModelResponse
from evalclaw.models.context_budget import LLMContextWindowError
from evalclaw.protocols.tool import ToolCall, ToolResult
from evalclaw.quality import analysis
from evalclaw.quality.analysis_context import AnalysisContext, size
from evalclaw.types import BenchmarkConfig


def large_payload():
    tasks = [{"id": f"task-{i}", "prompt": "材料/证据~data " * 3000, "reference_answer": "answer"} for i in range(200)]
    results = [{"item_id": t["id"], "target_id": "target", "score": i % 2,
                "judge_reasoning": "specific finding " * 4000, "error": None} for i, t in enumerate(tasks)]
    return {"benchmark": {"objective": "Evaluate", "tasks": tasks}, "main_run": {"results": results},
            "verification_history": [{"iteration": 1, "tasks": tasks[:12], "run": {"results": results[:12]}}],
            "remaining_probe_iterations": 2, "max_probe_tasks": 100}


def test_all_item_identities_scores_and_full_text_remain_reachable(tmp_path):
    payload = large_payload()
    payload["verification_history"][0]["evidence_assessments"] = [{
        "iteration": 0, "item_id": "task-199", "target_id": "target", "status": "confirmed_task_defect",
        "reason": "Scorer is invalid", "evidence": ["saved artifact"],
    }]
    context = AnalysisContext(payload, tmp_path, "deepseek-flash")
    view = json.loads(context.initial["content"])
    assert size(context.initial) < context.budget
    catalog = view["item_index"]
    assert len(catalog) == 212
    assert [r["score"] for r in catalog[:200]] == [i % 2 for i in range(200)]
    row = catalog[199]
    assert row["assessment_status"] == "confirmed_task_defect"
    assert view["controls"] == {"remaining_probe_iterations": 2, "max_probe_tasks": 100}
    chunks, offset = [], 0
    while True:
        result = context.read(ToolCall(id="read", name="read_analysis_context", arguments={
            "source": "request", "pointer": row["task"] + "/prompt", "offset": offset,
        }))
        assert result.error is None
        page = json.loads(result.content)
        chunks.append(page["content"])
        offset = page["next_offset"]
        if offset is None:
            break
    assert "".join(chunks) == payload["benchmark"]["tasks"][199]["prompt"]
    assert json.loads((tmp_path / "request.json").read_text()) == payload


def test_repeated_archiving_preserves_native_conversation_and_tool_contents(tmp_path):
    context = AnalysisContext({"objective": "Evaluate"}, tmp_path, "deepseek-flash")
    original = ToolResult(tool_call_id="tool-1", name="read_run_artifact", content="evidence" * 200000)
    bounded = context.bound_result(original)
    pointer = json.loads(bounded.content)
    assert context.sources[pointer["source"]] == original.content
    native = {"role": "assistant", "reasoning_content": "reason " * 100000,
              "tool_calls": [{"id": "tool-1", "type": "function", "function": {"name": "read_run_artifact", "arguments": "{}"}}]}
    messages = [context.initial, native, {"role": "tool", "tool_call_id": "tool-1", "content": bounded.content}]
    first = context.fit(messages)
    assert len(first) == 1 and first[0]["role"] == "user"
    first_archive = json.loads(first[0]["content"])["conversation_archive"]["source"]
    assert context.sources[first_archive] == messages
    second = context.fit([*first, {"role": "assistant", "content": "later " * 100000}])
    second_archive = json.loads(second[0]["content"])["conversation_archive"]["source"]
    assert context.sources[second_archive][0] == first[0]
    assert size(second) < context.budget
    page = context.read(ToolCall(id="read", name="read_analysis_context", arguments={
        "source": first_archive, "pointer": "/1/reasoning_content", "offset": 10, "max_chars": 100}))
    assert json.loads(page.content)["content"] == native["reasoning_content"][10:110]


def test_loop_recovers_from_provider_context_limit_without_rewriting_evidence(monkeypatch, tmp_path):
    payload = large_payload()
    calls = []
    def model(messages, **kwargs):
        calls.append(json.loads(json.dumps(messages)))
        if len(calls) == 1:
            raise LLMContextWindowError("provider window exceeded")
        assert any(t.name == "read_analysis_context" for t in kwargs["tools"])
        content = '{"analysis":"Completed","done":true}'
        return TargetToolModelResponse(adapter="openai", content=content, tool_calls=[],
                                       assistant_message={"role": "assistant", "content": content}, raw_response={})
    monkeypatch.setattr(analysis, "call_orchestrator_with_tools", model)
    result = analysis._run_analyser_tool_loop(payload, BenchmarkConfig(analyser_model="deepseek-flash"),
                                               trace_dir=tmp_path, artifact_dir=None)
    assert result["done"] is True
    assert len(calls) == 2
    assert size(calls[1]) < size(calls[0])
    assert json.loads((tmp_path / "context/request.json").read_text()) == payload
