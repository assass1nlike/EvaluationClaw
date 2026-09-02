"""Self-contained KaTeX assets for the HTML report viewers.

The reports are single-file documents that must render offline and be shared
as-is, so KaTeX is inlined rather than pulled from a CDN. This module bundles
KaTeX's JS/CSS plus every woff2 font (base64 data URIs) into one reusable HTML
fragment. It is generated once per process and cached.

To keep the vendored sources small in the repo, the raw minified assets live in
``evalclaw/reporting/_katex/``. The ``katex_assets()`` function returns the
``<style>``/``<script>`` block to paste into a template just before ``</head>``,
plus the auto-render boot call.

KaTeX version: 0.16.9 (npm ``katex``). Licensed under the MIT License.
"""
from __future__ import annotations

import base64
import re
from functools import lru_cache
from pathlib import Path

_KATEX_DIR = Path(__file__).parent / "_katex"
_FONT_ROOT = "fonts/"


def _asset_bytes(name: str) -> bytes:
    return (_KATEX_DIR / name).read_bytes()


@lru_cache(maxsize=1)
def _katex_css() -> str:
    """KaTeX stylesheet with every woff2 font inlined as a base64 data URI.

    Each ``@font-face`` declares three ``src`` fallbacks (woff2, woff, ttf).
    Only the woff2 is kept and embedded; the woff/ttf entries are dropped so
    modern browsers pick the inline woff2 while the file stays lean.
    """
    css = _asset_bytes("katex.min.css").decode("utf-8")

    def _embed_src(match: re.Match[str]) -> str:
        src = match.group(1)
        fonts = re.findall(r"url\(([^)]+)\)\s*format\(\"([^\"]+)\"\)", src)
        woff2 = next((path for path, fmt in fonts if fmt == "woff2"), None)
        woff = next((path for path, fmt in fonts if fmt == "woff"), None)
        woff2_data = _embed_woff2(woff2 or woff) if (woff2 or woff) else None
        return f"src:{woff2_data or src}"

    # Only the woff2 entries carry a src; the woff/ttf fallbacks are dropped so
    # modern browsers pick the inline woff2 while the file stays lean.
    css = re.sub(r"src:(url\([^)]*\)\s*format\(\"[^\"]*\"[^;]*?)(?=})", _embed_src, css)
    return css


def _embed_woff2(path: str | None) -> str | None:
    if not path:
        return None
    if not path.startswith(_FONT_ROOT):
        return None
    name = path[len(_FONT_ROOT) :]
    try:
        encoded = base64.b64encode(_asset_bytes(f"fonts/{name}")).decode("ascii")
    except FileNotFoundError:
        return None
    return f"url(data:font/woff2;base64,{encoded}) format(\"woff2\")"


@lru_cache(maxsize=1)
def katex_assets() -> str:
    """Return the inlined KaTeX block to inject before ``</head>``."""
    css = _katex_css()
    js = _asset_bytes("katex.min.js").decode("utf-8")
    auto_render = _asset_bytes("auto-render.min.js").decode("utf-8")
    boot = (
        "document.addEventListener('DOMContentLoaded', () => {"
        "  renderMathInElement(document.body, {"
        "    delimiters: ["
        "      {left: '$$', right: '$$', display: true},"
        "      {left: '\\\\[', right: '\\\\]', display: true},"
        "      {left: '\\\\begin{equation}', right: '\\\\end{equation}', display: true},"
        "      {left: '\\\\begin{align}', right: '\\\\end{align}', display: true},"
        "      {left: '\\\\(', right: '\\\\)', display: false},"
        "      {left: '$', right: '$', display: false}"
        "    ],"
        "    throwOnError: false,"
        "    strict: false"
        "  });"
        "});"
    )
    return (
        f"<style>{css}</style>\n"
        f"<script>{js}</script>\n"
        f"<script>{auto_render}</script>\n"
        f"<script>{boot}</script>\n"
    )


def inject_katex(template: str) -> str:
    """Insert the KaTeX block into a template just before ``</head>``."""
    return template.replace("</head>", katex_assets() + "</head>", 1)
