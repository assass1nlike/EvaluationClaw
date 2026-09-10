"""Fixed authoritative-source research for the Planner research ablation.

When ``ablation_authoritative_research`` is enabled, the Planner's research
tools switch from web search (a summary + citation-URL backend) to a fixed
catalog of authoritative sources, returning raw content instead of a
synthesized summary. The catalog is: a curated benchmark list, HuggingFace
datasets, Wikipedia, and arXiv.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import httpx

_ARXIV_API = "https://export.arxiv.org/api/query"
_WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
_HF_SPLITS_API = "https://datasets-server.huggingface.co/splits"
_HF_ROWS_API = "https://datasets-server.huggingface.co/rows"
_USER_AGENT = (
    "EvaluationClaw/0.1 "
    "(+https://github.com/assassinlike/EvaluationClaw; benchmark research)"
)

CURATED_DATASETS: dict[str, str] = {
    "MMLU-Pro": "TIGER-Lab/MMLU-Pro",
    "GPQA": "Idavidrein/gpqa",
    "HumanEval": "openai/openai_humaneval",
    "MBPP": "google-research-datasets/mbpp",
    "TruthfulQA": "truthfulqa/truthful_qa",
    "HellaSwag": "Rowan/hellaswag",
    "Winogrande": "allenai/winogrande",
    "HotpotQA": "hotpotqa/hotpot_qa",
    "SQuAD": "rajpurkar/squad",
    "AI2 ARC": "allenai/ai2_arc",
    "GSM8K": "openai/gsm8k",
    "MATH": "hendrycks/competition_math",
}


def _candidate(kind: str, ref: str, title: str, description: str = "") -> dict:
    return {"kind": kind, "ref": ref, "title": title, "description": description}


def _search_curated(query: str, limit: int) -> list[dict]:
    lowered = query.lower()
    results: list[dict] = []
    for name, dataset_id in CURATED_DATASETS.items():
        if name.lower() in lowered or lowered in name.lower():
            results.append(
                _candidate(
                    "hf_dataset",
                    f"hf://datasets/{dataset_id}",
                    name,
                    f"Curated benchmark ({dataset_id}).",
                )
            )
            if len(results) >= limit:
                break
    return results


def _search_hf(query: str, limit: int) -> list[dict]:
    try:
        from huggingface_hub import HfApi
    except Exception:
        return []
    try:
        datasets = HfApi().list_datasets(search=query, limit=limit)
    except Exception:
        return []
    results: list[dict] = []
    for dataset in datasets:
        dataset_id = getattr(dataset, "id", None) or getattr(dataset, "card_id", None)
        if not dataset_id:
            continue
        results.append(
            _candidate(
                "hf_dataset",
                f"hf://datasets/{dataset_id}",
                str(dataset_id),
                f"HuggingFace dataset: {dataset_id}.",
            )
        )
    return results[:limit]


def _search_wikipedia(query: str, limit: int) -> list[dict]:
    try:
        resp = httpx.get(
            _WIKIPEDIA_API,
            params={
                "action": "opensearch",
                "search": query,
                "limit": limit,
                "namespace": 0,
                "format": "json",
            },
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    titles = data[1] if len(data) > 1 else []
    descriptions = data[2] if len(data) > 2 else []
    urls = data[3] if len(data) > 3 else []
    results: list[dict] = []
    for index, title in enumerate(titles):
        url = urls[index] if index < len(urls) else ""
        description = descriptions[index] if index < len(descriptions) else ""
        results.append(_candidate("wikipedia", url, title, description[:300]))
    return results


def _search_arxiv(query: str, limit: int) -> list[dict]:
    try:
        resp = httpx.get(
            _ARXIV_API,
            params={"search_query": f"all:{query}", "start": 0, "max_results": limit},
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results: list[dict] = []
    for entry in root.findall("atom:entry", ns)[:limit]:
        title_el = entry.find("atom:title", ns)
        summary_el = entry.find("atom:summary", ns)
        id_el = entry.find("atom:id", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        summary = (
            re.sub(r"\s+", " ", (summary_el.text or "").strip())
            if summary_el is not None and summary_el.text
            else ""
        )
        url = (id_el.text or "").strip() if id_el is not None else ""
        if url:
            results.append(_candidate("arxiv", url, title, summary[:300]))
    return results


def search_sources(query: str, *, limit: int = 8) -> list[dict]:
    """Search the fixed authoritative catalog, returning raw-source candidates."""
    results: list[dict] = []
    results.extend(_search_curated(query, limit))
    results.extend(_search_hf(query, limit))
    results.extend(_search_wikipedia(query, limit))
    results.extend(_search_arxiv(query, limit))
    seen: set[str] = set()
    deduped: list[dict] = []
    for candidate in results:
        ref = candidate["ref"]
        if ref in seen:
            continue
        seen.add(ref)
        deduped.append(candidate)
    return deduped[:limit]


def _hf_dataset_rows(dataset_id: str, limit: int) -> str:
    attempts = [
        {"dataset": dataset_id, "config": "default", "split": "train"},
    ]
    try:
        resp = httpx.get(
            _HF_SPLITS_API,
            params={"dataset": dataset_id},
            timeout=20.0,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        splits = resp.json().get("splits", [])
        if splits:
            first = splits[0]
            attempts = [
                {
                    "dataset": dataset_id,
                    "config": first.get("config") or "default",
                    "split": first.get("split") or "train",
                }
            ]
    except Exception:
        pass
    for params in attempts:
        try:
            resp = httpx.get(
                _HF_ROWS_API,
                params={**params, "offset": 0, "length": limit},
                timeout=20.0,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
            )
            resp.raise_for_status()
            rows = resp.json().get("rows", [])
            if not rows:
                continue
            return "\n".join(
                json.dumps(item.get("row", {}), ensure_ascii=False, default=str)
                for item in rows
            )
        except Exception:
            continue
    return f"Could not load raw rows for hf://datasets/{dataset_id}."


def _wikipedia_text(title: str, max_chars: int = 4000) -> str:
    try:
        resp = httpx.get(
            _WIKIPEDIA_API,
            params={
                "action": "query",
                "prop": "extracts",
                "explaintext": 1,
                "titles": title,
                "format": "json",
            },
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        pages = resp.json().get("query", {}).get("pages", {})
        for page in pages.values():
            text = page.get("extract", "")
            if text:
                return re.sub(r"\s+", " ", text).strip()[:max_chars]
    except Exception:
        pass
    return f"Could not load the Wikipedia article for {title!r}."


def _arxiv_abstract(arxiv_id: str, max_chars: int = 4000) -> str:
    try:
        resp = httpx.get(
            _ARXIV_API,
            params={"id_list": arxiv_id, "max_results": 1},
            timeout=15.0,
            headers={"User-Agent": _USER_AGENT},
            follow_redirects=True,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entry = root.find("atom:entry", ns)
        if entry is not None:
            title = (entry.find("atom:title", ns).text or "").strip()
            summary = re.sub(r"\s+", " ", (entry.find("atom:summary", ns).text or "").strip())
            return f"Title: {title}\n\nAbstract: {summary}"[:max_chars]
    except Exception:
        pass
    return f"Could not load the arXiv abstract for {arxiv_id!r}."


def load_source(ref: str, *, limit: int = 5) -> str:
    """Load raw content from one source ref returned by :func:`search_sources`."""
    ref = (ref or "").strip()
    if ref.startswith("hf://datasets/"):
        return _hf_dataset_rows(ref[len("hf://datasets/") :], limit)
    if "en.wikipedia.org/wiki/" in ref:
        title = unquote(ref.rstrip("/").rsplit("/", 1)[-1])
        return _wikipedia_text(title)
    if "arxiv.org/abs/" in ref:
        arxiv_id = ref.rstrip("/").rsplit("/", 1)[-1]
        return _arxiv_abstract(arxiv_id)
    raise ValueError(f"Unsupported source ref: {ref!r}")


__all__ = ["CURATED_DATASETS", "load_source", "search_sources"]
