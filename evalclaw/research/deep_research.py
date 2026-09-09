"""Rendering for Planner-retained research source materials."""

from __future__ import annotations

from ..types import ResearchBrief


def render_brief_markdown(brief: ResearchBrief) -> str:
    """Render retained source materials as a readable Markdown document."""
    lines: list[str] = [
        "# Benchmark Source Materials",
        "",
        f"- Created at: {brief.created_at}",
        "",
    ]
    if brief.source_materials:
        lines.extend(["## Retained Sources", ""])
        for material in brief.source_materials:
            title = material.title or material.url
            lines.append(f"- **{title}** ({material.url}) — {len(material.content)} chars")
        lines.append("")
    if brief.research_notes:
        lines.extend(["## Notes", "", brief.research_notes, ""])
    return "\n".join(lines)
