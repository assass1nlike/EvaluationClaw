"""Compatibility shim for evalclaw.research.backends.

The web-search implementation moved to ``evalclaw/research/backends.py`` with a
pluggable :class:`~evalclaw.research.backends.SearchBackend` abstraction
(``gemini`` / ``keyless`` / ``none``). This module re-exports the historical
public names so existing imports keep working:

    from evalclaw.search import web_search, fetch_url_text, format_search_result
"""
from __future__ import annotations

from .research.backends import (
    DEFAULT_SEARCH_MODEL,
    GEMINI_API_BASE,
    GeminiBackend,
    KeylessBackend,
    NoneBackend,
    SearchBackend,
    SearchResult,
    fetch_url_text,
    format_search_result,
    get_backend,
    resolve_backend_name,
    web_search,
)

__all__ = [
    "DEFAULT_SEARCH_MODEL",
    "GEMINI_API_BASE",
    "GeminiBackend",
    "KeylessBackend",
    "NoneBackend",
    "SearchBackend",
    "SearchResult",
    "fetch_url_text",
    "format_search_result",
    "get_backend",
    "resolve_backend_name",
    "web_search",
]
