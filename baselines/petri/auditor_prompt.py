"""Auditor prompt variants for provider capabilities."""

from petri.solvers.prompts import AUDITOR_SYSTEM_PROMPT


def _without_prefill_section(prompt: str) -> str:
    start_marker = "\n## Prefill\n"
    end_marker = "\n## Ending Conversations\n"
    start = prompt.index(start_marker)
    end = prompt.index(end_marker, start)
    prompt = prompt[:start] + prompt[end:]
    return prompt.replace(
        "except in narrow contexts with the prefill tool as specified below.", "",
    )


NO_PREFILL_SYSTEM_PROMPT = _without_prefill_section(AUDITOR_SYSTEM_PROMPT)
