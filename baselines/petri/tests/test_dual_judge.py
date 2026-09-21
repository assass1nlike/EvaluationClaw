import asyncio
import json
import math

import pytest
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.log import read_eval_log
from petri.formatting.messages import format_messages
from petri.scorers.judge import JudgeStore, _format_dimensions, _format_scores_section
from petri.scorers.prompts import DIMENSIONS, SYSTEM_PROMPT as NATIVE_SYSTEM_PROMPT
from petri.transcript.transcript import Transcript

from requirement_judge import SYSTEM_PROMPT, RequirementJudgeStore
from run import save_results
import run
from test_scoring import JUDGMENT, REQUIREMENT, RUBRIC, run_audit


NATIVE_RESPONSE = (
    "<summary>Native assessment</summary><justification>Native reasons</justification><scores>\n"
    + "\n".join(f"{name}: 1/10" for name in DIMENSIONS) + "\n</scores>"
)
NATIVE_PROMPT = NATIVE_SYSTEM_PROMPT.format(
    dimensions=_format_dimensions(DIMENSIONS), scores_format=_format_scores_section(DIMENSIONS)
)


@pytest.mark.parametrize("failed", [None, "requirement_judge", "alignment_judge"])
def test_parallel_judges_keep_inputs_stores_and_failures_separate(tmp_path, failed):
    entered = {name: asyncio.Event() for name in ("requirement_judge", "alignment_judge")}
    requests = {name: [] for name in entered}
    prompt_roles = {SYSTEM_PROMPT: "requirement_judge", NATIVE_PROMPT: "alignment_judge"}

    async def generate(input, tools, tool_choice, config):
        name = prompt_roles[input[0].text]
        requests[name].append(input)
        entered[name].set()
        # Both model requests must start before either returns.
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in entered.values())), 3)
        content = json.dumps(JUDGMENT) if name == "requirement_judge" else NATIVE_RESPONSE
        return ModelOutput.from_content(model="judge", content="invalid" if name == failed else content)

    log, _ = run_audit(tmp_path, "both", [], judge_generate=generate)
    assert log.status == "success"
    sample = log.samples[0]
    assert set(sample.scores) == set(entered) - {failed}
    assert set(sample.metadata["judge_errors"]) == ({failed} if failed else set())
    assert {name: len(items) for name, items in requests.items()} == {
        name: 3 if name == failed else 1 for name in entered
    }
    transcript = Transcript.load(str(next((tmp_path / "transcripts").glob("*.json"))))
    history = format_messages(transcript.collect_messages(
        "target", add_only=True, indicate_rollbacks=True))
    for messages in requests["requirement_judge"]:
        assert len(messages) == 2
        assert json.loads(messages[1].text) == {
            "requirement": REQUIREMENT, "rubric": RUBRIC, "transcript": history,
        }
    for messages in requests["alignment_judge"]:
        assert len(messages) == 2
        assert messages[1].text.split("<transcript>", 1)[1].split("</transcript>", 1)[0].strip() == history.strip()
    assert sample.store_as(JudgeStore).messages[0].text == NATIVE_PROMPT
    assert sample.store_as(RequirementJudgeStore).messages[0].text == SYSTEM_PROMPT
    if failed == "alignment_judge":
        assert transcript.metadata.judge_output is None
    else:
        assert transcript.metadata.judge_output.scores == {name: 1 for name in DIMENSIONS}
    models = [e for e in sample.events if e.event == "model"]
    assert [e.role for e in models[:7]] == ["auditor", "auditor", "target", "auditor",
                                         "auditor", "target", "auditor"]
    assert all(e.role == "judge" for e in models[7:])

    if failed:
        with pytest.raises(RuntimeError):
            save_results(log, tmp_path, "both", REQUIREMENT)
    else:
        save_results(log, tmp_path, "both", REQUIREMENT)
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["primary_scorer"] == "requirement_judge"
    assert summary["scores"]["performance"] == (None if failed == "requirement_judge" else 5)
    assert summary["native_reference"]["scores"] == (
        None if failed == "alignment_judge" else {name: 1 for name in DIMENSIONS})
    assert (tmp_path / "native_judgment.json").exists()
    assert (tmp_path / "judgment.json").exists() == (failed != "requirement_judge")
    metrics = {s.name: s.metrics for s in log.results.scores}
    assert metrics["requirement_judge"] == {}
    if failed == "alignment_judge":
        # Inspect keeps a wildcard row with no samples when all native scores fail.
        assert set(metrics) == {"requirement_judge", "*"}
        empty = next(s for s in log.results.scores if s.scorer == "alignment_judge")
        assert empty.scored_samples == 0
        assert set(empty.metrics) == {"mean", "stderr"}
        assert all(math.isnan(metric.value) for metric in empty.metrics.values())
    else:
        assert set(metrics) == {"requirement_judge", *DIMENSIONS}
        for name in DIMENSIONS:
            assert {key: value.value for key, value in metrics[name].items()} == {
                "mean": 1, "stderr": 0,
            }


def test_dual_scoring_preserves_native_and_requirement_results(tmp_path):
    both, _ = run_audit(tmp_path / "both", "both", [json.dumps(JUDGMENT), NATIVE_RESPONSE])
    requirement, _ = run_audit(tmp_path / "requirement", "requirement", [json.dumps(JUDGMENT)])
    native, _ = run_audit(tmp_path / "native", "native", [NATIVE_RESPONSE])
    assert both.status == requirement.status == native.status == "success"
    for name, single in [("requirement_judge", requirement), ("alignment_judge", native)]:
        assert both.samples[0].scores[name] == single.samples[0].scores[name]


def test_default_runner_exports_primary_and_reference(tmp_path, monkeypatch):
    actions = [("send_message", {"message": "What is 2+2?"}), ("end_conversation", {})]
    outputs = {
        "mockllm/auditor": [ModelOutput.for_tool_call(
            model="auditor", tool_name=name, tool_arguments=args) for name, args in actions],
        "mockllm/target": [ModelOutput.from_content(model="target", content="4")],
        "mockllm/judge": lambda messages, *args: ModelOutput.from_content(
            model="judge", content={SYSTEM_PROMPT: json.dumps(JUDGMENT),
                                    NATIVE_PROMPT: NATIVE_RESPONSE}[messages[0].text]),
    }

    def model(name, **kwargs):
        return get_model(name, custom_outputs=outputs[name], **kwargs)

    monkeypatch.setattr(run, "get_model", model)
    monkeypatch.setattr("sys.argv", ["run.py", "--auditor", "mockllm/auditor",
                                    "--target", "mockllm/target", "--judge", "mockllm/judge",
                                    "--base-url", "https://example.invalid",
                                    "--seed", "61",
                                    "--output-dir", str(tmp_path / "run")])
    run.main()
    directory = tmp_path / "run"
    config = json.loads((directory / "config.json").read_text())
    assert config["scoring"] == "both"
    assert config["seed"] == 61
    assert all(role["seed"] == 61 for role in config["generation"].values())
    log = read_eval_log(next((directory / "logs").glob("*.eval")))
    assert all(event.config.seed == 61 for event in log.samples[0].events if event.event == "model")
    assert config["generation"]["judge"]["max_connections"] == 2
    assert config["generation"]["auditor"]["max_connections"] == 1
    assert config["generation"]["target"]["max_connections"] == 1
    summary = json.loads((directory / "summary.json").read_text())
    assert summary["scores"] == {"performance": 5}
    assert summary["native_reference"]["scores"] == {name: 1 for name in DIMENSIONS}
    assert (directory / "native_judge_prompt.txt").read_text() == NATIVE_PROMPT


def test_native_aggregates_match_standalone_over_multiple_samples(tmp_path):
    values = [{name: 1 + index % 5 + 2 * sample for index, name in enumerate(DIMENSIONS)}
              for sample in range(3)]
    responses = ["<summary>Test</summary><justification>Test</justification><scores>\n"
                 + "\n".join(f"{name}: {value}/10" for name, value in sample.items())
                 + "\n</scores>" for sample in values]
    both_responses = [item for response in responses for item in (json.dumps(JUDGMENT), response)]
    both, _ = run_audit(tmp_path / "both", "both", both_responses, sample_count=3)
    native, _ = run_audit(tmp_path / "native", "native", responses, sample_count=3)
    assert both.status == native.status == "success"
    assert len(both.samples) == len(native.samples) == 3
    for sample in both.samples:
        assert sum(e.event == "model" and e.role == "judge" for e in sample.events) == 2
    # Check the persisted log as well as the in-memory result.
    saved = read_eval_log(next((tmp_path / "both" / "logs").glob("*.eval")))
    for log in (both, saved):
        actual = {score.name: score for score in log.results.scores}
        assert set(actual) == {"requirement_judge", *DIMENSIONS}
        assert actual["requirement_judge"].metrics == {}
        for expected in native.results.scores:
            result = actual[expected.name]
            assert result.scorer == expected.scorer == "alignment_judge"
            assert result.scored_samples == expected.scored_samples == 3
            assert result.unscored_samples == expected.unscored_samples == 0
            assert result.metrics == expected.metrics
            assert set(expected.metrics) == {"mean", "stderr"}
            assert expected.metrics["mean"].value == values[1][expected.name]
            assert expected.metrics["stderr"].value == pytest.approx(2 / math.sqrt(3))
