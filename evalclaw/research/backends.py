"""Pluggable web-search backends for EvalClaw research.

Backends all return the same :class:`SearchResult` shape so callers can swap
between them transparently:

  - ``gemini``  : Gemini Google-Search grounding (requires GEMINI_API_KEY).
  - ``ablation-keyless`` : combined free sources (arXiv API + Wikipedia API +
                  DuckDuckGo HTML), no API key required. This is the ablation
                  baseline, not a first-class backend.
  - ``none``    : disabled, always returns ``None``.

The historical helpers ``web_search``, ``fetch_url_text`` and
``format_search_result`` live here; ``evalclaw/search.py`` re-exports them for
backwards compatibility.
"""
from __future__ import annotations

import hashlib
import html as _html
import mimetypes
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlsplit

import httpx

GEMINI_API_BASE = os.environ.get(
    "GEMINI_API_BASE", "https://generativelanguage.googleapis.com/v1beta"
)
DEFAULT_SEARCH_MODEL = "gemini-2.5-flash-lite"

_GEMINI_SEARCH_RETRIES = 3
_GEMINI_TRANSIENT_STATUS = {429, 500, 502, 503, 504}

ARXIV_API = "https://export.arxiv.org/api/query"
WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
WIKIPEDIA_SUMMARY = "https://en.wikipedia.org/api/rest_v1/page/summary"
DUCKDUCKGO_HTML = "https://html.duckduckgo.com/html/"

_USER_AGENT = (
    "EvaluationClaw/0.1 "
    "(+https://github.com/assassinlike/EvaluationClaw; automated benchmark research)"
)
_TERMINAL_SOURCE_STATUSES = {401, 403, 407, 429}
_FETCH_STATE_LOCK = threading.RLock()
_FETCH_CACHE: dict[tuple[str, int], str | None] = {}
_FETCH_BLOCKED_ORIGINS: dict[str, int | str] = {}
_FETCH_ORIGIN_LOCKS: dict[str, threading.Lock] = {}


@dataclass
class SearchResult:
    """Synthesized answer from a grounded search, with source citations."""

    content: str
    citations: list[dict] = field(default_factory=list)  # [{"url": ..., "title": ...}]


class SearchError(RuntimeError):
    """A search backend failed for a reason callers may need to surface."""


class SearchConfigurationError(SearchError):
    """The selected search backend cannot run with the current configuration."""


class SearchTimeoutError(SearchError, TimeoutError):
    """A search request timed out and may be retried by the caller."""


class SearchBackendError(SearchError):
    """The selected backend returned an operational/API error."""


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------
def download_url_file(
    url: str,
    destination_dir: Path,
    *,
    max_bytes: int,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Download one HTTP(S) response to a framework-managed directory."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("url must be an absolute HTTP(S) URL")
    if max_bytes <= 0:
        raise ValueError("download byte limit has been exhausted")

    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=timeout,
        headers={"User-Agent": _USER_AGENT},
    ) as response:
        response.raise_for_status()
        declared_size = response.headers.get("content-length")
        if declared_size and declared_size.isdigit() and int(declared_size) > max_bytes:
            raise ValueError(f"download exceeds the {max_bytes}-byte limit")

        resolved_url = str(response.url)
        media_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
        original_name = Path(unquote(urlsplit(resolved_url).path)).name or "download"
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name).strip("._")
        safe_name = safe_name[:120] or "download"
        suffix = Path(safe_name).suffix[:16]
        if not suffix and media_type:
            suffix = mimetypes.guess_extension(media_type) or ""
        stem = Path(safe_name).stem[:80] or "download"
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:12]
        filename = f"{stem}-{digest}{suffix}"

        destination_dir.mkdir(parents=True, exist_ok=True)
        target = destination_dir / filename
        partial = destination_dir / f".{filename}.part"
        size = 0
        try:
            with partial.open("wb") as file:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError(f"download exceeds the {max_bytes}-byte limit")
                    file.write(chunk)
            partial.replace(target)
        except Exception:
            partial.unlink(missing_ok=True)
            raise

    return {
        "source_url": url,
        "resolved_url": resolved_url,
        "path": str(target.resolve()),
        "filename": filename,
        "media_type": media_type or "application/octet-stream",
        "size_bytes": size,
    }


def fetch_url_text(url: str, max_chars: int = 4000, timeout: float = 10.0) -> str | None:
    """Fetch a URL and return its plain-text content, stripped of HTML.

    Returns None if the request fails or the page is not text/html.
    """
    if not url.startswith(("http://", "https://")):
        return None
    cache_key = (url, max_chars)
    origin = urlsplit(url).netloc.lower()
    with _FETCH_STATE_LOCK:
        if cache_key in _FETCH_CACHE:
            return _FETCH_CACHE[cache_key]
        if origin in _FETCH_BLOCKED_ORIGINS:
            return None
        origin_lock = _FETCH_ORIGIN_LOCKS.setdefault(origin, threading.Lock())
    with origin_lock:
        with _FETCH_STATE_LOCK:
            if cache_key in _FETCH_CACHE:
                return _FETCH_CACHE[cache_key]
            if origin in _FETCH_BLOCKED_ORIGINS:
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
                with _FETCH_STATE_LOCK:
                    _FETCH_CACHE[cache_key] = None
                return None
            html = resp.text
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            with _FETCH_STATE_LOCK:
                _FETCH_CACHE[cache_key] = None
                if status in _TERMINAL_SOURCE_STATUSES:
                    first_block = origin not in _FETCH_BLOCKED_ORIGINS
                    _FETCH_BLOCKED_ORIGINS[origin] = status
                else:
                    first_block = False
            if first_block:
                print(f"  [fetch] disabled {origin} for this run after HTTP {status}.")
            else:
                print(f"  [fetch] {origin} returned HTTP {status}; skipping this URL.")
            return None
        except httpx.TimeoutException:
            with _FETCH_STATE_LOCK:
                _FETCH_CACHE[cache_key] = None
                first_timeout = origin not in _FETCH_BLOCKED_ORIGINS
                _FETCH_BLOCKED_ORIGINS[origin] = "timeout"
            if first_timeout:
                print(f"  [fetch] disabled {origin} for this run after timeout.")
            return None
        except Exception as exc:
            with _FETCH_STATE_LOCK:
                _FETCH_CACHE[cache_key] = None
            print(f"  [fetch] {origin} failed once ({type(exc).__name__}); skipping this URL.")
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
    result = text[:max_chars]
    with _FETCH_STATE_LOCK:
        _FETCH_CACHE[cache_key] = result
    return result


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

    def search_or_raise(self, query: str) -> SearchResult | None:
        """Search while surfacing operational failures to a strict caller."""
        return self.search(query)


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
        try:
            return self.search_or_raise(query)
        except SearchError as exc:
            print(f"  [search] {exc}")
            return None

    def search_or_raise(self, query: str) -> SearchResult | None:
        key = self.api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise SearchConfigurationError(
                "Gemini search requires GEMINI_API_KEY or a Gemini search API key."
            )

        endpoint = f"{GEMINI_API_BASE}/models/{self.model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": query}]}],
            "tools": [{"google_search": {}}],
        }

        last_error: Exception | None = None
        for attempt in range(_GEMINI_SEARCH_RETRIES):
            try:
                resp = httpx.post(
                    endpoint,
                    headers={"Content-Type": "application/json", "x-goog-api-key": key},
                    json=payload,
                    timeout=30.0,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except httpx.TimeoutException as exc:
                last_error = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in _GEMINI_TRANSIENT_STATUS:
                    raise SearchBackendError(f"Gemini search failed: {exc}") from exc
                last_error = exc
            except httpx.TransportError as exc:
                last_error = exc
            except Exception as exc:
                raise SearchBackendError(f"Gemini search failed: {exc}") from exc
            if attempt + 1 < _GEMINI_SEARCH_RETRIES:
                print(
                    f"  [search] Gemini attempt {attempt + 1}/{_GEMINI_SEARCH_RETRIES} "
                    f"failed ({type(last_error).__name__}); retrying."
                )
                time.sleep(2**attempt)
        else:
            if isinstance(last_error, httpx.TimeoutException):
                raise SearchTimeoutError("Gemini search timed out.") from last_error
            raise SearchBackendError(f"Gemini search failed: {last_error}") from last_error

        if "error" in data:
            message = data["error"].get("message", data["error"])
            raise SearchBackendError(f"Gemini API error: {message}")

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
    source degrades silently for normal callers. Strict callers receive an
    error when no source succeeds. Content is a concatenation of source
    snippets; citations are ``[{"title", "url"}]``.
    """

    name = "ablation-keyless"

    def __init__(
        self,
        *,
        max_results: int = 4,
        timeout: float = 15.0,
        min_source_interval_s: float = 0.5,
    ) -> None:
        self.max_results = max_results
        self.timeout = timeout
        self.min_source_interval_s = max(0.0, min_source_interval_s)
        self._state_lock = threading.RLock()
        self._source_locks = {
            name: threading.Lock() for name in ("arxiv", "wikipedia", "duckduckgo")
        }
        self._query_cache: dict[tuple[str, str], list[dict]] = {}
        self._disabled_sources: dict[str, int | str] = {}
        self._last_source_request: dict[str, float] = {}

    def reset(self) -> None:
        """Clear per-process cache and circuit-breaker state."""
        with self._state_lock:
            self._query_cache.clear()
            self._disabled_sources.clear()
            self._last_source_request.clear()

    def _run_source(self, name: str, source, query: str, *, strict: bool) -> list[dict]:
        normalized_query = " ".join(query.lower().split())
        cache_key = (name, normalized_query)
        with self._state_lock:
            if cache_key in self._query_cache:
                return self._query_cache[cache_key]
            if name in self._disabled_sources:
                if strict:
                    self._disabled_sources.pop(name, None)
                else:
                    return []
        with self._source_locks[name]:
            with self._state_lock:
                if cache_key in self._query_cache:
                    return self._query_cache[cache_key]
                if name in self._disabled_sources:
                    if strict:
                        self._disabled_sources.pop(name, None)
                    else:
                        return []
                elapsed = time.monotonic() - self._last_source_request.get(name, 0.0)
            if elapsed < self.min_source_interval_s:
                time.sleep(self.min_source_interval_s - elapsed)
            try:
                entries = source(query)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                with self._state_lock:
                    self._last_source_request[name] = time.monotonic()
                    if not strict and status in _TERMINAL_SOURCE_STATUSES:
                        first_block = name not in self._disabled_sources
                        self._disabled_sources[name] = status
                    else:
                        first_block = False
                detail = (
                    f"disabled keyless source {name} for this run after HTTP {status}"
                    if first_block
                    else f"keyless source {name} returned HTTP {status}"
                )
                if strict:
                    raise SearchBackendError(detail) from exc
                print(f"  [search] {detail}; query skipped.")
                return []
            except httpx.TimeoutException:
                with self._state_lock:
                    self._last_source_request[name] = time.monotonic()
                    if not strict:
                        first_timeout = name not in self._disabled_sources
                        self._disabled_sources[name] = "timeout"
                    else:
                        first_timeout = False
                if strict:
                    raise SearchTimeoutError(f"keyless source {name} timed out.") from None
                if first_timeout:
                    print(f"  [search] disabled keyless source {name} for this run after timeout.")
                return []
            except Exception as exc:
                with self._state_lock:
                    self._last_source_request[name] = time.monotonic()
                detail = f"keyless source {name} failed ({type(exc).__name__}): {exc}"
                if strict:
                    raise SearchBackendError(detail) from exc
                print(f"  [search] {detail}; query skipped.")
                return []
            with self._state_lock:
                self._query_cache[cache_key] = entries
                self._last_source_request[name] = time.monotonic()
            return entries

    def search(self, query: str) -> SearchResult | None:
        return self._search(query, strict=False)

    def search_or_raise(self, query: str) -> SearchResult | None:
        return self._search(query, strict=True)

    def _search(self, query: str, *, strict: bool) -> SearchResult | None:
        snippets: list[str] = []
        citations: list[dict] = []
        seen: set[str] = set()
        failures: list[SearchError] = []
        source_status: dict[str, str] = {}

        sources = (
            ("arxiv", self._arxiv),
            ("wikipedia", self._wikipedia),
            ("duckduckgo", self._duckduckgo),
        )
        with ThreadPoolExecutor(max_workers=len(sources)) as executor:
            requests = {
                name: executor.submit(self._run_source, name, source, query, strict=strict)
                for name, source in sources
            }
        for name, _source in sources:
            try:
                entries = requests[name].result()
            except SearchError as exc:
                failures.append(exc)
                source_status[name] = f"error: {exc}"
                continue
            source_status[name] = "ok" if entries else "no_results"
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
            if strict and failures:
                error_type = (
                    SearchTimeoutError
                    if all(isinstance(error, SearchTimeoutError) for error in failures)
                    else SearchBackendError
                )
                details = "; ".join(
                    f"{name}={status}" for name, status in source_status.items()
                )
                raise error_type(
                    f"Keyless search request failed for query {query!r}: {details}."
                ) from failures[0]
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
_VALID_BACKENDS = {"auto", "gemini", "ablation-keyless", "none"}
_KEYLESS_BACKEND = KeylessBackend()
_NONE_BACKEND = NoneBackend()


def resolve_backend_name(setting: str | None, *, gemini_key: str | None = None) -> str:
    """Resolve an effective backend name.

    Precedence: explicit setting (not ``auto``) > gemini (the default) >
    ``ablation-keyless``. An explicit ``auto`` still means "gemini if a Gemini
    key is available, ablation-keyless otherwise".
    """
    name = (setting or "gemini").lower()
    if name not in _VALID_BACKENDS:
        name = "gemini"
    if name != "auto":
        return name
    key = gemini_key or os.environ.get("GEMINI_API_KEY", "")
    return "gemini" if key else "ablation-keyless"


def get_backend(
    setting: str | None = "gemini",
    *,
    gemini_api_key: str | None = None,
    gemini_model: str = DEFAULT_SEARCH_MODEL,
    resolve_redirects: bool = True,
) -> SearchBackend:
    """Instantiate a backend from a setting name using the auto precedence."""
    name = resolve_backend_name(setting, gemini_key=gemini_api_key)
    if name == "none":
        return _NONE_BACKEND
    if name == "ablation-keyless":
        return _KEYLESS_BACKEND
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
    backend: str | None = "gemini",
    raise_on_error: bool = False,
) -> SearchResult | None:
    """Run a web search using the selected backend.

    Backend selection (see :func:`resolve_backend_name`): explicit ``backend``
    setting > gemini (the default) > ablation-keyless.

    ``api_key``/``model`` retain their historical meaning for the Gemini
    backend. They are only forwarded to Gemini when they look Gemini-shaped so
    an orchestrator key/model for a different provider (e.g. Azure) does not
    clobber the ``GEMINI_API_KEY`` environment fallback.

    Set ``raise_on_error`` when configuration and operational failures must be
    distinguished from a valid search that found no results.
    """
    gemini_key = api_key if (model or "").startswith("gemini") else None
    gemini_model = model if (model or "").startswith("gemini") else DEFAULT_SEARCH_MODEL
    backend_name = resolve_backend_name(backend, gemini_key=gemini_key)
    if backend_name == "none":
        error = SearchConfigurationError("Web search is disabled by search_backend='none'.")
        if raise_on_error:
            raise error
        return None
    impl = get_backend(
        backend_name,
        gemini_api_key=gemini_key,
        gemini_model=gemini_model,
        resolve_redirects=resolve_redirects,
    )
    try:
        return impl.search_or_raise(query) if raise_on_error else impl.search(query)
    except SearchError as exc:
        if raise_on_error:
            raise
        print(f"  [search] {exc}")
        return None


def reset_network_state() -> None:
    """Start a fresh research run with empty caches and circuit breakers.

    Call this only when no research requests are active. Requests made during
    one pipeline run still share cache and source-health state.
    """
    _KEYLESS_BACKEND.reset()
    with _FETCH_STATE_LOCK:
        _FETCH_CACHE.clear()
        _FETCH_BLOCKED_ORIGINS.clear()
        _FETCH_ORIGIN_LOCKS.clear()


def _reset_network_state_for_tests() -> None:
    """Backward-compatible test helper for resetting research network state."""
    reset_network_state()
