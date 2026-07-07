"""Pluggable web-search backends for EvalClaw research.

Backends all return the same :class:`SearchResult` shape so callers can swap
between them transparently:

  - ``gemini``  : Gemini Google-Search grounding (requires GEMINI_API_KEY).
  - ``keyless`` : combined free sources (arXiv API + Wikipedia API + DuckDuckGo
                  HTML), no API key required.
  - ``none``    : disabled, always returns ``None``.

The historical helpers ``web_search``, ``fetch_url_text`` and
``format_search_result`` live here; ``evalclaw/search.py`` re-exports them for
backwards compatibility.
"""
from __future__ import annotations

import html as _html
import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote_plus, urlsplit

import httpx

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_SEARCH_MODEL = "gemini-2.5-flash-lite"

ARXIV_API = "https://export.arxiv.org/api/query"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"
DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"

_USER_AGENT = "Mozilla/5.0 (compatible; evalclaw/1.0)"


@dataclass
class SearchResult:
    """Synthesized answer from a grounded search, with source citations."""

    content: str
    citations: list[dict] = field(default_factory=list)  # [{"url": ..., "title": ...}]


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------
def fetch_url_text(url: str, max_chars: int = 4000, timeout: float = 10.0) -> str | None:
    """Fetch a URL and return its plain-text content, stripped of HTML.

    Returns None if the request fails or the page is not text/html.
    """
    if not url.startswith(("http://", "https://")):
        return None
    try:
        resp = httpx.get(
            url,
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT},
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
    lines = ["=== Web Search Results ===", result.content]
    if result.citations:
        lines.append("\nSources:")
        for i, c in enumerate(result.citations[:10], 1):
            title = c.get("title") or c["url"]
            lines.append(f"  [{i}] {title}  {c['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Backend abstraction
# ---------------------------------------------------------------------------
class SearchBackend:
    """Base class for search backends."""

    name = "base"

    def search(self, query: str) -> SearchResult | None:  # pragma: no cover - abstract
        raise NotImplementedError


class NoneBackend(SearchBackend):
    """Disabled backend that always returns no result."""

    name = "none"

    def search(self, query: str) -> SearchResult | None:
        return None


class GeminiBackend(SearchBackend):
    """Gemini Google-Search grounding backend.

    Ported unchanged from the original ``search.py`` implementation:
      - POST to generateContent with tools=[{google_search:{}}]
      - Extract AI-synthesized content + groundingChunks citations
      - Follow citation redirect URLs to resolve final URLs
    """

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = DEFAULT_SEARCH_MODEL,
        resolve_redirects: bool = True,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.resolve_redirects = resolve_redirects

    @staticmethod
    def _resolve_redirect_url(url: str, client: httpx.Client) -> str:
        """Follow a single redirect to get the real destination URL."""
        if "vertexaisearch.cloud.google.com" not in url:
            return url
        try:
            resp = client.head(url, follow_redirects=True, timeout=5.0)
            return str(resp.url)
        except Exception:
            return url

    def search(self, query: str) -> SearchResult | None:
        key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            return None

        endpoint = f"{GEMINI_API_BASE}/models/{self.model}:generateContent"
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

        content = "\n".join(
            part.get("text", "")
            for part in (candidate.get("content", {}).get("parts") or [])
            if part.get("text")
        ) or "No content returned"

        raw_citations = [
            {"url": chunk["web"]["uri"], "title": chunk["web"].get("title")}
            for chunk in (candidate.get("groundingMetadata", {}).get("groundingChunks") or [])
            if chunk.get("web", {}).get("uri")
        ]

        citations: list[dict] = []
        if self.resolve_redirects and raw_citations:
            with httpx.Client() as client:
                for i in range(0, len(raw_citations), 10):
                    batch = raw_citations[i : i + 10]
                    citations.extend(
                        {
                            "url": self._resolve_redirect_url(c["url"], client),
                            "title": c.get("title"),
                        }
                        for c in batch
                    )
        else:
            citations = raw_citations

        return SearchResult(content=content, citations=citations)


class KeylessBackend(SearchBackend):
    """Free, no-API-key backend combining arXiv, Wikipedia and DuckDuckGo.

    Every source is best-effort and wrapped in try/except so a single failing
    source degrades silently. Content is a concatenation of source snippets;
    citations are ``[{"title", "url"}]``.
    """

    name = "keyless"

    def __init__(self, *, max_results: int = 4, timeout: float = 15.0) -> None:
        self.max_results = max_results
        self.timeout = timeout

    def search(self, query: str) -> SearchResult | None:
        snippets: list[str] = []
        citations: list[dict] = []
        seen: set[str] = set()

        for source in (self._arxiv, self._wikipedia, self._duckduckgo):
            try:
                entries = source(query)
            except Exception as exc:  # degrade silently per source
                print(f"  [search] keyless source {source.__name__} failed: {exc}")
                entries = []
            for entry in entries:
                url = entry.get("url", "")
                if not url or url in seen:
                    continue
                seen.add(url)
                title = entry.get("title") or url
                citations.append({"url": url, "title": title})
                snippet = entry.get("snippet", "")
                block = f"- {title} ({url})"
                if snippet:
                    block += f"\n  {snippet}"
                snippets.append(block)

        if not citations and not snippets:
            return None

        content = "\n".join(snippets) if snippets else "No content returned"
        return SearchResult(content=content, citations=citations)

    # -- individual sources -------------------------------------------------
    def _arxiv(self, query: str) -> list[dict]:
        params = {
            "search_query": f"all:{query}",
            "start": "0",
            "max_results": str(self.max_results),
        }
        resp = httpx.get(
            ARXIV_API,
            params=params,
            timeout=self.timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        return self._parse_arxiv_atom(resp.text, self.max_results)

    @staticmethod
    def _parse_arxiv_atom(xml_text: str, limit: int) -> list[dict]:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_text)
        entries: list[dict] = []
        for entry in root.findall("atom:entry", ns)[:limit]:
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            id_el = entry.find("atom:id", ns)
            title = (title_el.text or "").strip() if title_el is not None else ""
            summary = (summary_el.text or "").strip() if summary_el is not None else ""
            url = (id_el.text or "").strip() if id_el is not None else ""
            summary = re.sub(r"\s+", " ", summary)
            if url:
                entries.append(
                    {"title": title, "url": url, "snippet": summary[:500]}
                )
        return entries

    def _wikipedia(self, query: str) -> list[dict]:
        params = {
            "action": "opensearch",
            "search": query,
            "limit": str(min(self.max_results, 3)),
            "namespace": "0",
            "format": "json",
        }
        resp = httpx.get(
            WIKIPEDIA_API,
            params=params,
            timeout=self.timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
        # opensearch returns [query, [titles], [descriptions], [urls]]
        titles = data[1] if len(data) > 1 else []
        descriptions = data[2] if len(data) > 2 else []
        urls = data[3] if len(data) > 3 else []
        entries: list[dict] = []
        for i, title in enumerate(titles):
            url = urls[i] if i < len(urls) else ""
            snippet = descriptions[i] if i < len(descriptions) else ""
            if not snippet:
                snippet = self._wikipedia_summary(title)
            entries.append({"title": title, "url": url, "snippet": snippet[:500]})
        return entries

    def _wikipedia_summary(self, title: str) -> str:
        try:
            resp = httpx.get(
                f"{WIKIPEDIA_SUMMARY}/{quote_plus(title.replace(' ', '_'))}",
                timeout=self.timeout,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
            resp.raise_for_status()
            return str(resp.json().get("extract", ""))
        except Exception:
            return ""

    def _duckduckgo(self, query: str) -> list[dict]:
        resp = httpx.get(
            DUCKDUCKGO_HTML,
            params={"q": query},
            timeout=self.timeout,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        html = resp.text
        entries: list[dict] = []
        # Result links look like <a class="result__a" href="URL">TITLE</a>
        for match in re.finditer(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        ):
            url = self._resolve_ddg_url(_html.unescape(match.group(1)))
            title = _html.unescape(re.sub(r"<[^>]+>", "", match.group(2))).strip()
            if url:
                entries.append({"title": title, "url": url, "snippet": ""})
            if len(entries) >= self.max_results:
                break
        return entries

    @staticmethod
    def _resolve_ddg_url(url: str) -> str:
        """Normalize a DuckDuckGo result href to the real destination URL.

        DDG HTML results use protocol-relative redirect links of the form
        ``//duckduckgo.com/l/?uddg=<url-encoded target>&rut=...``.
        """
        if url.startswith("//"):
            url = "https:" + url
        if "duckduckgo.com/l/" in url:
            target = parse_qs(urlsplit(url).query).get("uddg")
            if target and target[0].startswith(("http://", "https://")):
                return target[0]
        return url


# ---------------------------------------------------------------------------
# Selection helpers
# ---------------------------------------------------------------------------
_VALID_BACKENDS = {"auto", "gemini", "keyless", "none"}


def resolve_backend_name(setting: str | None, *, gemini_key: str | None = None) -> str:
    """Resolve an effective backend name.

    Precedence: explicit setting (not ``auto``) > gemini if a Gemini key is
    available > keyless otherwise.
    """
    name = (setting or "auto").lower()
    if name not in _VALID_BACKENDS:
        name = "auto"
    if name != "auto":
        return name
    key = gemini_key or os.environ.get("GEMINI_API_KEY", "")
    return "gemini" if key else "keyless"


def get_backend(
    setting: str | None = "auto",
    *,
    gemini_api_key: str | None = None,
    gemini_model: str = DEFAULT_SEARCH_MODEL,
    resolve_redirects: bool = True,
) -> SearchBackend:
    """Instantiate a backend from a setting name using the auto precedence."""
    name = resolve_backend_name(setting, gemini_key=gemini_api_key)
    if name == "none":
        return NoneBackend()
    if name == "keyless":
        return KeylessBackend()
    return GeminiBackend(
        api_key=gemini_api_key,
        model=gemini_model,
        resolve_redirects=resolve_redirects,
    )


def web_search(
    query: str,
    *,
    api_key: str | None = None,
    model: str = DEFAULT_SEARCH_MODEL,
    resolve_redirects: bool = True,
    backend: str | None = "auto",
) -> SearchResult | None:
    """Run a web search using the selected backend.

    Backend selection (see :func:`resolve_backend_name`): explicit ``backend``
    setting > gemini if GEMINI_API_KEY available > keyless otherwise.

    ``api_key``/``model`` retain their historical meaning for the Gemini
    backend. They are only forwarded to Gemini when they look Gemini-shaped so
    an orchestrator key/model for a different provider (e.g. Azure) does not
    clobber the ``GEMINI_API_KEY`` environment fallback.
    """
    gemini_key = api_key if (model or "").startswith("gemini") else None
    gemini_model = model if (model or "").startswith("gemini") else DEFAULT_SEARCH_MODEL
    impl = get_backend(
        backend,
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        resolve_redirects=resolve_redirects,
    )
    return impl.search(query)
