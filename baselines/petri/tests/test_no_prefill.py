import inspect

from auditor_prompt import NO_PREFILL_SYSTEM_PROMPT
from petri.solvers.prompts import AUDITOR_SYSTEM_PROMPT
from petri.tools import send_message, send_tool_call_result


def test_no_prefill_prompt_removes_prefill_instructions():
    assert "## Prefill" in AUDITOR_SYSTEM_PROMPT
    assert "## Prefill" not in NO_PREFILL_SYSTEM_PROMPT
    assert "prefill" not in NO_PREFILL_SYSTEM_PROMPT.lower()


def test_no_prefill_tools_have_no_prefix_argument():
    assert list(inspect.signature(send_message(prefill=False)).parameters) == ["message"]
    assert list(inspect.signature(send_tool_call_result(prefill=False)).parameters) == [
        "tool_call_id", "result", "status"
    ]
