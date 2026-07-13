"""Persistent text-browser tools for Docker-backed agent tasks."""
from __future__ import annotations

from ..protocols.tool import ToolSpec, object_schema

DOCKER_BROWSER_RUNTIME_PATH = "/opt/evalclaw/browser_runtime.py"
DOCKER_BROWSER_CONFIG_PATH = "/opt/evalclaw/browser_config.json"
DOCKER_BROWSER_PORT = 8765


def docker_browser_tool_specs() -> list[ToolSpec]:
    """Return the canonical tools exposed by the Docker browser runtime."""
    selector = {
        "selector": {
            "type": "string",
            "description": "CSS or Playwright text selector from the latest browser snapshot.",
        }
    }
    return [
        ToolSpec(
            name="browser_navigate",
            description="Navigate to an allowed HTTP(S) URL and return a text/DOM snapshot.",
            parameters=object_schema(
                {"url": {"type": "string", "description": "Absolute or relative URL."}},
                required=["url"],
            ),
        ),
        ToolSpec(
            name="browser_snapshot",
            description="Inspect the current page as text plus actionable element selectors.",
            parameters=object_schema(),
        ),
        ToolSpec(
            name="browser_click",
            description="Click the first element matching a selector from the current page snapshot.",
            parameters=object_schema(selector, required=["selector"]),
        ),
        ToolSpec(
            name="browser_fill",
            description="Replace the value of an input or textarea.",
            parameters=object_schema(
                {**selector, "value": {"type": "string"}},
                required=["selector", "value"],
            ),
        ),
        ToolSpec(
            name="browser_select",
            description="Select an option in a select element by value or visible label.",
            parameters=object_schema(
                {
                    **selector,
                    "value": {"type": "string"},
                    "label": {"type": "string"},
                },
                required=["selector"],
            ),
        ),
        ToolSpec(
            name="browser_check",
            description="Set a checkbox or radio control to the requested checked state.",
            parameters=object_schema(
                {**selector, "checked": {"type": "boolean"}},
                required=["selector"],
            ),
        ),
        ToolSpec(
            name="browser_press",
            description="Press a keyboard key on the selected element or page body.",
            parameters=object_schema(
                {
                    **selector,
                    "key": {"type": "string", "description": "Playwright key name such as Enter."},
                },
                required=["key"],
            ),
        ),
        ToolSpec(
            name="browser_get_text",
            description="Read the text content of the first element matching a selector.",
            parameters=object_schema(selector, required=["selector"]),
        ),
    ]


DOCKER_BROWSER_RUNTIME_SCRIPT = r'''#!/usr/bin/env python3
import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

CONFIG_PATH = Path("/opt/evalclaw/browser_config.json")
MAX_BODY_CHARS = 12000
MAX_ELEMENTS = 100


def _origin(url):
    parsed = urlsplit(url)
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""


def _read_json_stream(stream):
    raw = stream.read()
    if not raw:
        return {}
    value = json.loads(raw.decode("utf-8"))
    return value if isinstance(value, dict) else {}


class BrowserRuntime:
    def __init__(self, config):
        self.config = config
        self.start_url = str(config.get("start_url") or "about:blank")
        configured_origins = config.get("allowed_origins")
        self.allowed_origins = {
            str(value).rstrip("/")
            for value in configured_origins or [_origin(self.start_url)]
            if str(value).strip()
        }
        self.timeout_ms = max(1000, int(config.get("timeout_ms") or 15000))
        self.startup_timeout_s = max(1, int(config.get("startup_timeout") or 45))
        self.lock = threading.Lock()
        self.playwright = sync_playwright().start()
        launch_options = {
            "headless": True,
            "args": ["--no-sandbox"],
            "viewport": {"width": 1280, "height": 900},
        }
        if config.get("executable_path"):
            launch_options["executable_path"] = str(config["executable_path"])
        self.context = self.playwright.chromium.launch_persistent_context(
            "/tmp/evalclaw-browser-profile", **launch_options
        )
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(self.timeout_ms)
        if self.start_url != "about:blank":
            deadline = time.monotonic() + self.startup_timeout_s
            while True:
                try:
                    self._navigate(self.start_url)
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.5)

    def _allowed_url(self, value):
        candidate = urljoin(self.page.url if self.page.url != "about:blank" else self.start_url, value)
        parsed = urlsplit(candidate)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("Only HTTP(S) navigation is allowed.")
        if self.allowed_origins and _origin(candidate).rstrip("/") not in self.allowed_origins:
            raise ValueError(f"Navigation origin is not allowed: {_origin(candidate)}")
        return candidate

    def _navigate(self, value):
        target = self._allowed_url(value)
        self.page.goto(target, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return target

    def _settle(self):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=min(self.timeout_ms, 5000))
        except Exception:
            pass
        self.page.wait_for_timeout(150)

    def snapshot(self):
        body_text = ""
        try:
            body_text = self.page.locator("body").inner_text(timeout=min(self.timeout_ms, 5000))
        except Exception:
            body_text = ""
        js = """(els) => els.slice(0, 100).map((el, index) => {
          const tag = el.tagName.toLowerCase();
          const text = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().replace(/\\s+/g, ' ').slice(0, 180);
          const name = el.getAttribute('name') || '';
          let selector = '';
          if (el.id) selector = '#' + CSS.escape(el.id);
          else if (name) selector = tag + '[name="' + CSS.escape(name) + '"]';
          else if (text && (tag === 'a' || tag === 'button')) selector = 'text=' + text;
          else selector = tag + ':nth-of-type(' + (Array.from(el.parentElement ? el.parentElement.children : [el]).filter(x => x.tagName === el.tagName).indexOf(el) + 1) + ')';
          return {
            index, selector, tag, type: el.getAttribute('type') || '', name,
            text, value: 'value' in el ? String(el.value).slice(0, 180) : '',
            checked: 'checked' in el ? Boolean(el.checked) : null,
            disabled: Boolean(el.disabled), href: el.href || '',
            options: tag === 'select' ? Array.from(el.options).map(o => ({value: o.value, label: o.text, selected: o.selected})) : []
          };
        })"""
        elements = self.page.locator(
            "a,button,input,textarea,select,[role=button],[contenteditable=true]"
        ).evaluate_all(js)
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "body_text": body_text[:MAX_BODY_CHARS],
            "elements": elements[:MAX_ELEMENTS],
        }

    def perform(self, tool, args):
        with self.lock:
            result = {}
            if tool == "browser_navigate":
                self._navigate(str(args.get("url") or ""))
            elif tool == "browser_snapshot":
                pass
            elif tool == "browser_click":
                self.page.locator(str(args.get("selector") or "")).first.click()
                self._settle()
            elif tool == "browser_fill":
                self.page.locator(str(args.get("selector") or "")).first.fill(str(args.get("value") or ""))
            elif tool == "browser_select":
                locator = self.page.locator(str(args.get("selector") or "")).first
                if args.get("label") not in (None, ""):
                    locator.select_option(label=str(args.get("label")))
                else:
                    locator.select_option(value=str(args.get("value") or ""))
            elif tool == "browser_check":
                locator = self.page.locator(str(args.get("selector") or "")).first
                if bool(args.get("checked", True)):
                    locator.check()
                else:
                    locator.uncheck()
            elif tool == "browser_press":
                selector = str(args.get("selector") or "body")
                self.page.locator(selector).first.press(str(args.get("key") or ""))
                self._settle()
            elif tool == "browser_get_text":
                selector = str(args.get("selector") or "")
                result["text"] = self.page.locator(selector).first.inner_text()
            else:
                raise ValueError(f"Unknown browser tool: {tool}")
            result["snapshot"] = self.snapshot()
            return result

    def close(self):
        self.context.close()
        self.playwright.stop()


RUNTIME = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _send(self, status, value):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
            result = RUNTIME.perform(str(payload.get("tool") or ""), payload.get("args") or {})
            self._send(200, {"ok": True, "result": result})
        except Exception as exc:
            self._send(400, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})


def serve(port):
    global RUNTIME
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    RUNTIME = BrowserRuntime(config)
    server = HTTPServer(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    finally:
        RUNTIME.close()


def call(port, tool):
    args = _read_json_stream(__import__("sys").stdin.buffer)
    payload = json.dumps({"tool": tool, "args": args}).encode("utf-8")
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/call",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            print(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"))
        raise SystemExit(1) from exc


def ping(port):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:
        print(response.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "call", "ping"])
    parser.add_argument("tool", nargs="?")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "serve":
        serve(args.port)
    elif args.command == "call":
        call(args.port, args.tool or "")
    else:
        ping(args.port)


if __name__ == "__main__":
    main()
'''


__all__ = [
    "DOCKER_BROWSER_CONFIG_PATH",
    "DOCKER_BROWSER_PORT",
    "DOCKER_BROWSER_RUNTIME_PATH",
    "DOCKER_BROWSER_RUNTIME_SCRIPT",
    "docker_browser_tool_specs",
]
