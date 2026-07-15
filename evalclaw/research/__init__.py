"""EvalClaw research subpackage: pluggable search backends + deep research."""
from __future__ import annotations

from .backends import (
    DEFAULT_SEARCH_MODEL,
    GeminiBackend,
    KeylessBackend,
    NoneBackend,
    SearchBackend,
    SearchResult,
    fetch_url_text,
    format_search_result,
    get_backend,
    reset_network_state,
    resolve_backend_name,
    web_search,
)
from .deep_research import compact_brief_context, render_brief_markdown, run_deep_research

__all__ = [
    "DEFAULT_SEARCH_MODEL",
    "GeminiBackend",
    "KeylessBackend",
    "NoneBackend",
    "SearchBackend",
    "SearchResult",
    "compact_brief_context",
    "fetch_url_text",
    "format_search_result",
    "get_backend",
    "render_brief_markdown",
    "reset_network_state",
    "resolve_backend_name",
    "run_deep_research",
    "web_search",
]
