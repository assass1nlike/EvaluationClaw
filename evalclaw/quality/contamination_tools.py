"""Read-only search, navigation, document inspection, and exact-match evidence tools."""
from __future__ import annotations

import json
import subprocess
import tarfile
import zipfile
from concurrent.futures import CancelledError
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from ..diagnostics import redact_secrets, write_json
from ..protocols.tool import ToolCall, ToolResult, ToolSpec, object_schema, validate_tool_call
from ..research.backends import (
    SearchError,
    download_url_file,
    fetch_url_links,
    fetch_url_text,
    web_search,
)
from ..research.documents import ResourceArchive
from ..research.documents import document_text as _document_text
from ..research.tools import search_failure_result
from ..types import BenchmarkConfig, BenchmarkItem, ContaminationItemResult, ContaminationMatch
from .laaj import _item_payload
from .laaj_tools import _declared_text

SOURCE_CHARACTER_LIMIT = 100_000
DOWNLOAD_BYTE_LIMIT = 64 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 64
_STRING = {"type": "string"}
_PAGE = {"offset": {"type": "integer", "minimum": 0}, "max_chars": {"type": "integer", "minimum": 1, "maximum": 20000}}


def _tool(name: str, description: str, properties: dict, required: list[str]) -> ToolSpec:
    return ToolSpec(name=name, description=description, parameters=object_schema(properties, required=required))


RESEARCH_TOOLS = [
    _tool("search_web", "Search for sources; refine queries as evidence changes. Search summaries are leads, not verified source text.", {"query": _STRING}, ["query"]),
    _tool("fetch_url", "Read original HTML or text at a URL and register a source. For binary documents use download_source.", {"url": _STRING}, ["url"]),
    _tool("list_url_links", "Inspect static page links to find deeper pages or downloadable files (up to 200 links).", {"url": _STRING}, ["url"]),
    _tool("download_source", "Download text, PDF, ZIP, or TAR resources. Read archive members without extracting or executing them. Returns document IDs for read_source.", {"url": _STRING}, ["url"]),
    _tool("read_source", "Read another portion of a fetched source or archive member.", {"source_id": _STRING, **_PAGE}, ["source_id"]),
    _tool("confirm_overlap", "Verify a substantial contiguous exact passage occurs both in a task field/file and in a retrieved original source. Only verified passages become evidence.", {
        "source_id": _STRING, "text": _STRING,
        "area": {"type": "string", "enum": ["task", "visible", "runtime", "hidden", "session", "image_build", "asset", "definition"]},
        "path": _STRING,
    }, ["source_id", "text"]),
]


def normalize(text: str) -> str:
    return " ".join(text.split())


def _strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _strings(child)


class ContaminationResearchTools:
    def __init__(self, item: BenchmarkItem, config: BenchmarkConfig,
                 result: ContaminationItemResult, directory: Path):
        self.item, self.config, self.result, self.directory = item, config, result, directory
        self.sources: dict[str, dict[str, Any]] = {}
        self.visited: set[str] = set()
        self.evidence: dict[str, Any] = {"item_id": item.id, "tool_trace": [], "sources": self.sources}

    def record(self, call: ToolCall, result: ToolResult) -> None:
        if result.error != "tool_budget_exhausted":
            self.result.tool_calls += 1
        if result.error:
            self.result.limitations.append(f"{call.name}: {result.content}")
        self.evidence["tool_trace"].append({"call": call.model_dump(mode="json"), "result": result.model_dump(mode="json")})
        write_json(self.directory / "research.json", self.evidence, redact=True)
        write_json(self.directory / "result.json", self.result.model_dump(mode="json"), redact=True)

    def _url(self, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc:
            raise ValueError("Use an absolute HTTP(S) URL.")
        if value not in self.visited and len(self.visited) >= self.config.contamination_max_sources:
            raise ValueError("Distinct source URL budget exhausted; inspect already retrieved sources.")
        self.visited.add(value)
        return value

    def _register(self, url: str, text: str, location: str = "", *, truncated: bool = False) -> str:
        for source_id, source in self.sources.items():
            if source["url"] == url and source["location"] == location:
                return source_id
        source_id = f"source_{len(self.sources) + 1}"
        truncated = truncated or len(text) > SOURCE_CHARACTER_LIMIT
        self.sources[source_id] = {"url": url, "location": location,
                                   "text": text[:SOURCE_CHARACTER_LIMIT], "truncated": truncated}
        if url not in self.result.checked_urls:
            self.result.checked_urls.append(url)
        if truncated:
            self.result.limitations.append(f"Source text truncated to {SOURCE_CHARACTER_LIMIT} characters: {url} {location}")
        return source_id

    def _read(self, source_id: str, offset: int = 0, max_chars: int = 8000) -> dict:
        source = self.sources[source_id]
        if offset < 0 or not 1 <= max_chars <= 20000:
            raise ValueError("offset must be nonnegative and max_chars must be in 1..20000.")
        text = source["text"]
        end = offset + max_chars
        return {"source_id": source_id, "url": source["url"], "location": source["location"],
                "content": text[offset:end], "next_offset": end if end < len(text) else None,
                "total_characters": len(text), "source_truncated": source["truncated"]}

    def _download(self, url: str) -> dict:
        downloaded = download_url_file(url, self.directory / "downloads", max_bytes=DOWNLOAD_BYTE_LIMIT)
        path = Path(downloaded["path"])
        ids = []
        skipped = []
        archive_bytes = 0

        def add(name: str, data: bytes, truncated: bool = False):
            try:
                text = _document_text(data, self.directory)
                if text is None:
                    skipped.append(name)
                else:
                    ids.append(self._register(url, text, name, truncated=truncated))
            except (OSError, ValueError, subprocess.SubprocessError) as exc:
                skipped.append(f"{name}: {exc}")

        def read_member(file, name, size):
            nonlocal archive_bytes
            prefix = file.read(5)
            remaining = DOWNLOAD_BYTE_LIMIT - archive_bytes
            limit = remaining if prefix == b"%PDF-" else min(SOURCE_CHARACTER_LIMIT + 1, remaining)
            if limit < 5 or (prefix == b"%PDF-" and size > limit):
                skipped.append(f"{name}: archive read budget exceeded")
                return
            data = prefix + file.read(limit - len(prefix))
            archive_bytes += len(data)
            add(name, data, size > len(data))

        if zipfile.is_zipfile(path) or tarfile.is_tarfile(path):
            with ResourceArchive(path) as archive:
                members = [member for member in archive.entries if archive.describe(member)["kind"] == "file"]
                for member in members[:MAX_ARCHIVE_MEMBERS]:
                    with archive.open(member) as file:
                        info = archive.describe(member)
                        read_member(file, info["name"], info["size_bytes"])
                if len(members) > MAX_ARCHIVE_MEMBERS:
                    skipped.append("Archive member limit reached.")
        else:
            add("", path.read_bytes())
        if skipped:
            self.result.limitations.append(f"Unreadable or uninspected members at {url}: {skipped}")
        if not ids:
            raise ValueError(f"No readable text extracted from {url}; unsupported content or missing pdftotext for PDF. {skipped}")
        return {"download": downloaded, "documents": [self._read(sid, max_chars=500) for sid in ids], "skipped": skipped}

    def _confirm(self, args: dict) -> dict:
        source = self.sources[args["source_id"]]
        text = args["text"]
        quote = normalize(text)
        if len(quote) < self.config.contamination_min_overlap_chars:
            raise ValueError(f"The contiguous overlap must contain at least {self.config.contamination_min_overlap_chars} normalized characters.")
        area, path = args.get("area", "task"), args.get("path", "")
        from ..protocols.task_view import definition_data
        task_source = definition_data(self.item) if self.item.content is not None else _item_payload(self.item)
        task_texts = _strings(task_source) if area == "task" else [_declared_text(self.item, area, path) or ""]
        if not any(quote in normalize(value) for value in task_texts):
            raise ValueError("Passage does not occur verbatim in the specified task field/file.")
        normalized = normalize(source["text"])
        offset = normalized.find(quote)
        if offset < 0:
            raise ValueError("Passage does not occur verbatim in the retrieved original source.")
        match = ContaminationMatch(url=source["url"], source_location=source["location"],
                                   task_area=area, task_path=path, task_quote=text,
                                   source_excerpt=normalized[max(0, offset - 1000):offset + len(quote) + 1000])
        if match not in self.result.matches:
            self.result.matches.append(match)
        return {"confirmed": True, "match": match.model_dump(mode="json"), "total_matches": len(self.result.matches)}

    def dispatch(self, call: ToolCall) -> ToolResult:
        try:
            errors = validate_tool_call(call, RESEARCH_TOOLS)
            if errors:
                raise ValueError(" ".join(errors))
            args = call.arguments
            if call.name == "search_web":
                if len(self.result.queries) >= self.config.contamination_max_queries:
                    raise ValueError("Search query budget exhausted; inspect existing leads.")
                query = args["query"].strip()
                if not query or redact_secrets(query) != query:
                    raise ValueError("Use a nonempty query without credentials.")
                self.result.queries.append(query)
                found = web_search(query, backend=self.config.search_backend, raise_on_error=True)
                payload = {"content": found.content if found else "", "citations": found.citations if found else [],
                           "note": "Search output is a lead, not verified original text."}
            elif call.name == "fetch_url":
                url = self._url(args["url"])
                text = fetch_url_text(url, max_chars=SOURCE_CHARACTER_LIMIT + 1)
                if not text:
                    raise ValueError("No readable page text; explore links or use download_source for files.")
                payload = self._read(self._register(url, text))
            elif call.name == "list_url_links":
                payload = fetch_url_links(self._url(args["url"]), max_links=200)
                if payload is None:
                    raise ValueError("Could not read static page links.")
                if len(payload.get("links", [])) >= 200:
                    self.result.limitations.append("Link listing reached its 200-link limit.")
            elif call.name == "download_source":
                payload = self._download(self._url(args["url"]))
            elif call.name == "read_source":
                payload = self._read(**args)
            else:
                payload = self._confirm(args)
            return ToolResult(tool_call_id=call.id, name=call.name, content=json.dumps(redact_secrets(payload), ensure_ascii=False))
        except CancelledError:
            raise
        except SearchError as exc:
            return search_failure_result(call, exc)
        except Exception as exc:
            return ToolResult(tool_call_id=call.id, name=call.name, error="research_tool_error",
                              content=str(redact_secrets(f"{type(exc).__name__}: {exc}")))
