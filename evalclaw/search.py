"""Evalclaw: Web search via Gemini Google Search grounding.

Replicates the logic in extensions/google/src/gemini-web-search-provider.ts:
  - POST to generateContent with tools=[{google_search:{}}]
  - Extract AI-synthesized content + groundingChunks citations
  - Follow citation redirect URLs to resolve final URLs

Requires GEMINI_API_KEY (same key used for LLM calls).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_SEARCH_MODEL = "gemini-2.5-flash-lite"


@dataclass
class SearchResult:
    """Synthesized answer from Gemini grounded search, with source citations."""
    content: str
    citations: list[dict] = field(default_factory=list)  # [{"url": ..., "title": ...}]


def _resolve_redirect_url(url: str, client: httpx.Client) -> str:
    """Follow a single redirect to get the real destination URL.

    Gemini grounding citations often come as vertexaisearch.cloud.google.com
    redirect links. We do one HEAD request to resolve them.
    """
    if "vertexaisearch.cloud.google.com" not in url:
        return url
    try:
        resp = client.head(url, follow_redirects=True, timeout=5.0)
        return str(resp.url)
    except Exception:
        return url


def web_search(
    query: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_SEARCH_MODEL,
    resolve_redirects: bool = True,
) -> SearchResult | None:
    """Run a Gemini-grounded Google search.

    Returns a SearchResult with synthesized content and source citations,
    or None if the search fails (so callers can degrade gracefully).
    """
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None

    endpoint = f"{GEMINI_API_BASE}/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": query}]}],
        "tools": [{"google_search": {}}],
    }

    try:
        resp = httpx.post(
            endpoint,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"  [search] Gemini search failed: {exc}")
        return None

    if "error" in data:
        print(f"  [search] Gemini API error: {data['error'].get('message', data['error'])}")
        return None

    candidate = (data.get("candidates") or [{}])[0]

    # Synthesized text content
    content = "\n".join(
        part.get("text", "")
        for part in (candidate.get("content", {}).get("parts") or [])
        if part.get("text")
    ) or "No content returned"

    # Raw citations from groundingChunks
    raw_citations = [
        {"url": chunk["web"]["uri"], "title": chunk["web"].get("title")}
        for chunk in (candidate.get("groundingMetadata", {}).get("groundingChunks") or [])
        if chunk.get("web", {}).get("uri")
    ]

    # Optionally resolve redirect URLs (batch of 10, same as TS implementation)
    citations: list[dict] = []
    if resolve_redirects and raw_citations:
        with httpx.Client() as client:
            for i in range(0, len(raw_citations), 10):
                batch = raw_citations[i : i + 10]
                citations.extend(
                    {"url": _resolve_redirect_url(c["url"], client), "title": c.get("title")}
                    for c in batch
                )
    else:
        citations = raw_citations

    return SearchResult(content=content, citations=citations)


def fetch_url_text(url: str, max_chars: int = 4000, timeout: float = 10.0) -> str | None:
    """Fetch a URL and return its plain-text content, stripped of HTML.

    Returns None if the request fails or the page is not text/html.
    """
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; evalclaw/1.0)"},
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "text" not in content_type and "html" not in content_type:
            return None
        html = resp.text
    except Exception as exc:
        print(f"  [fetch] {url} failed: {exc}")
        return None

    # Strip <script> and <style> blocks first
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all remaining HTML tags
    text = re.sub(r"<[^>]+>", " ", html)
    # Decode common HTML entities
    for entity, char in [("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                          ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]:
        text = text.replace(entity, char)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def format_search_result(result: SearchResult) -> str:
    """Format a SearchResult for injection into the generator context."""
    lines = ["=== 网络搜索结果 ===", result.content]
    if result.citations:
        lines.append("\n来源：")
        for i, c in enumerate(result.citations[:10], 1):
            title = c.get("title") or c["url"]
            lines.append(f"  [{i}] {title}  {c['url']}")
    return "\n".join(lines)
