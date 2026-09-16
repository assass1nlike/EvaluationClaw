"""Visual-grounding MCP server.

Exposes a `visual_grounding` tool that accepts a screenshot path and a
question, sends them to a vision-language model, and returns a textual
analysis (typically with pixel coordinates of UI elements). The creation
prompt under `extras/research/software_as_env/creation_audit/memory/`
references this tool by the MCP name `visual-grounding`.

This is NOT wired into `gym-anything-extras`; you set it up yourself,
either as an MCP server in your agent CLI of choice, or by importing
`visual_grounding` directly. See ./README.md for setup.

Providers (selected via SCREENSHOT_QUERY_PROVIDER):
  - "gemini"     — Google AI Studio (default model: gemini-3-flash-preview)
  - "databricks" — Databricks-hosted Claude (default model: databricks-claude-sonnet-4-5)
  - "openai"     — Any OpenAI-compatible endpoint via SCREENSHOT_QUERY_BASE_URL

Required environment variables:
  - SCREENSHOT_QUERY_PROVIDER   (default: "gemini")
  - SCREENSHOT_QUERY_MODEL      (provider-specific default)
  - SCREENSHOT_QUERY_BASE_URL   (overrides provider's default endpoint)
  - SCREENSHOT_QUERY_API_KEY    (preferred), or fall back to
    GEMINI_API_KEY / DATABRICKS_TOKEN / OPENAI_API_KEY for the chosen provider.
"""

from __future__ import annotations

import base64
import os
import sys
from io import BytesIO
from pathlib import Path

import openai
from mcp.server.fastmcp import FastMCP
from PIL import Image

# Optional: load a sibling .env so users can keep keys out of shells/configs.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass


# ---------------------------------------------------------------------------
# System prompt for the VLM
# ---------------------------------------------------------------------------

CLAUDE_SYSTEM_PROMPT = """<SYSTEM_CAPABILITY>
* You are utilising an Ubuntu virtual machine with internet access.
* You can feel free to install Ubuntu applications with your bash tool. Use curl instead of wget.
* To open firefox, please just click on the firefox icon. Note, firefox-esr is what is installed on your system.
* Using bash tool you can start GUI applications, but you need to set export DISPLAY=:1 and use a subshell. For example "(DISPLAY=:1 xterm &)". GUI apps run with bash tool will appear within your desktop environment, but they may take some time to appear. Take a screenshot to confirm it did.
* When using your bash tool with commands that are expected to output very large quantities of text, redirect into a tmp file and use str_replace_based_edit_tool or `grep -n -B <lines before> -A <lines after> <query> <filename>` to confirm output.
* When viewing a page it can be helpful to zoom out so that you can see everything on the page. Either that, or make sure you scroll down to see everything before deciding something isn't available.
* When using your computer function calls, they take a while to run and send back to you. Where possible/feasible, try to chain multiple of these calls all into one function calls request.
</SYSTEM_CAPABILITY>

<IMPORTANT>
* When using Firefox, if a startup wizard appears, IGNORE IT. Do not even click "skip this step". Instead, click on the address bar where it says "Search or enter address", and enter the appropriate search term or URL there.
* If the item you are looking at is a pdf, if after taking a single screenshot of the pdf it seems that you want to read the entire document instead of trying to continue to read the pdf from your screenshots + navigation, determine the URL, use curl to download the pdf, install and use pdftotext to convert it to a text file, and then read that text file directly with your str_replace_based_edit_tool.
</IMPORTANT>"""


# ---------------------------------------------------------------------------
# MCP server registration
# ---------------------------------------------------------------------------

mcp = FastMCP(
    name="visual-grounding",
    instructions=(
        "Visual grounding assistant for GUI environments. "
        "Analyzes screenshots to identify UI elements, read text, locate "
        "buttons/icons, and provide pixel coordinates for mouse interactions. "
        "Coordinates are returned in 1280x720 scale and must be converted to "
        "the actual display resolution."
    ),
)


# ---------------------------------------------------------------------------
# Image + provider helpers
# ---------------------------------------------------------------------------


def _encode_image(image_path: str) -> tuple[str, int, int]:
    """Load image, resize to 1280x720 for the VLM, return (b64, orig_w, orig_h)."""
    image = Image.open(image_path)
    orig_w, orig_h = image.size
    resized = image.resize((1280, 720))
    buf = BytesIO()
    resized.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8"), orig_w, orig_h


def _api_key_for(provider: str) -> str:
    """Look up an API key, preferring the generic SCREENSHOT_QUERY_API_KEY."""
    key = os.getenv("SCREENSHOT_QUERY_API_KEY", "")
    if key:
        return key
    fallback = {
        "gemini": "GEMINI_API_KEY",
        "databricks": "DATABRICKS_TOKEN",
        "openai": "OPENAI_API_KEY",
    }.get(provider, "")
    return os.getenv(fallback, "") if fallback else ""


def _query_gemini(messages: list, model: str) -> str:
    client = openai.OpenAI(
        base_url=os.getenv(
            "SCREENSHOT_QUERY_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta/openai/",
        ),
        api_key=_api_key_for("gemini"),
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
    )
    text = response.choices[0].message.content
    if isinstance(text, list):
        text = next(
            (block["text"] for block in text if block.get("type") == "text"),
            str(text),
        )
    return text


def _query_databricks(messages: list, model: str) -> str:
    base_url = os.getenv(
        "SCREENSHOT_QUERY_BASE_URL",
        "",
    )
    if not base_url:
        raise RuntimeError(
            "SCREENSHOT_QUERY_BASE_URL must be set for the databricks provider "
            "(e.g. https://<workspace>.cloud.databricks.com/serving-endpoints)."
        )
    client = openai.OpenAI(
        base_url=base_url,
        api_key=_api_key_for("databricks"),
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
        extra_body={"thinking": {"type": "enabled", "budget_tokens": 2048}},
    )
    text = response.choices[0].message.content
    if isinstance(text, list):
        text = next(
            (block["text"] for block in text if block.get("type") == "text"),
            str(text),
        )
    return text


def _query_openai(messages: list, model: str) -> str:
    client = openai.OpenAI(
        base_url=os.getenv("SCREENSHOT_QUERY_BASE_URL"),
        api_key=_api_key_for("openai"),
    )
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        max_tokens=4096,
    )
    text = response.choices[0].message.content
    if isinstance(text, list):
        text = next(
            (block["text"] for block in text if block.get("type") == "text"),
            str(text),
        )
    return text


# ---------------------------------------------------------------------------
# Tool entry point
# ---------------------------------------------------------------------------


_DEFAULT_MODELS = {
    "gemini": "gemini-3-flash-preview",
    "databricks": "databricks-claude-sonnet-4-5",
    "openai": "gpt-4o",
}


@mcp.tool()
def visual_grounding(question: str, screenshot_path: str) -> str:
    """Analyze a GUI screenshot to ground UI elements, read on-screen text, and locate interactive components.

    Use this tool when you need to:
    - Find the pixel coordinates of a button, icon, menu item, or any UI element
    - Read text or labels visible on screen
    - Understand the current state of a GUI application
    - Determine where to click, type, or drag to accomplish a task
    - Identify dialog boxes, tooltips, error messages, or status indicators

    Coordinates in the response are normalized to 1280x720 and must be scaled
    to the actual display resolution (returned alongside the response).

    Args:
        question: What you want to know about the screenshot
            (e.g. "Where is the Save button?", "What text is in the status bar?").
        screenshot_path: Absolute path to the screenshot image file.
    """
    if not os.path.isfile(screenshot_path):
        return f"Error: file not found: {screenshot_path}"

    b64, orig_w, orig_h = _encode_image(screenshot_path)

    messages = [
        {"role": "system", "content": CLAUDE_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": question},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                },
            ],
        },
    ]

    provider = os.getenv("SCREENSHOT_QUERY_PROVIDER", "gemini").lower()
    model = os.getenv("SCREENSHOT_QUERY_MODEL") or _DEFAULT_MODELS.get(provider)
    if model is None:
        return f"Error: unknown provider {provider!r}; expected gemini|databricks|openai"

    if provider == "gemini":
        text = _query_gemini(messages, model)
    elif provider == "databricks":
        text = _query_databricks(messages, model)
    elif provider == "openai":
        text = _query_openai(messages, model)
    else:
        return f"Error: unknown provider {provider!r}; expected gemini|databricks|openai"

    return (
        f"{text}\n\n"
        f"NOTE: Any coordinates above are in 1280x720 scale. "
        f"Original screenshot resolution: {orig_w}x{orig_h}."
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
