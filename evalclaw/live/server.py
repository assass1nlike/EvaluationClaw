"""Minimal HTTP server for real-time pipeline visualisation.

Two modes of operation:

1. **Standalone** (``evalclaw serve``): starts a persistent server that
   aggregates events from all ``generate`` processes via HTTP POST.

2. **Embedded** (``evalclaw generate --live``): the generate process itself
   starts a lightweight server that only serves its own run, then stops when
   the run completes.

In both modes the browser points at::

    http://localhost:{port}/              – run list
    http://localhost:{port}/run/{run_id}  – single run live view
    http://localhost:{port}/events/{id}   – SSE stream
    http://localhost:{port}/api/runs      – JSON list of runs (polling fallback)
    http://localhost:{port}/api/push      – POST endpoint for remote events
"""
from __future__ import annotations

import json
import queue
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .bus import _SENTINEL, event_json, global_bus

_DEFAULT_PORT = 8800
_server: HTTPServer | None = None
_server_port: int | None = None
_server_lock = threading.Lock()
_start_lock = threading.Lock()


def _load_template() -> str:
    tmpl = Path(__file__).parent / "template.html"
    return tmpl.read_text(encoding="utf-8")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:  # silence default logging
        pass

    def _send(self, code: int, content_type: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self._send(code, "application/json; charset=utf-8", body)

    def _send_html(self, html: str, code: int = 200) -> None:
        body = html.encode("utf-8")
        self._send(code, "text/html; charset=utf-8", body)

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path == "/" or path == "/index.html":
            tmpl = _load_template()
            page = tmpl.replace("__PAGE_MODE__", "list")
            page = page.replace("__RUN_ID__", "")
            self._send_html(page)

        elif path.startswith("/run/"):
            run_id = path[5:]
            bus = global_bus().get(run_id)
            if bus is None:
                self._send_html("<h1>Run not found</h1>", 404)
                return
            tmpl = _load_template()
            page = tmpl.replace("__PAGE_MODE__", "run")
            page = page.replace("__RUN_ID__", run_id)
            self._send_html(page)

        elif path.startswith("/events/"):
            run_id = path[8:]
            self._serve_sse(run_id)

        elif path == "/api/runs":
            self._send_json(global_bus().list_runs())

        elif path.startswith("/api/snapshot/"):
            run_id = path[14:]
            bus = global_bus().get(run_id)
            if bus is None:
                self._send_json({"error": "not found"}, 404)
                return
            self._send_json(bus.snapshot())

        else:
            self._send_html("<h1>Not found</h1>", 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/api/push":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                self._send_json({"error": "bad json"}, 400)
                return
            run_id = data.get("run_id") or ""
            event = data.get("event") or {}
            if not run_id or not event:
                self._send_json({"error": "missing run_id or event"}, 400)
                return
            bus = global_bus().get(run_id)
            if bus is None:
                # Auto-create run when push arrives before register
                from .registry import register_run
                register_run(
                    run_id,
                    goal=str(data.get("goal") or ""),
                    created_at=str(data.get("created_at") or ""),
                )
                bus = global_bus().get(run_id)
            if bus is not None:
                bus.publish(event)
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "not found"}, 404)

    def _serve_sse(self, run_id: str) -> None:
        bus = global_bus().get(run_id)
        if bus is None:
            self._send_html("<h1>Run not found</h1>", 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = bus.subscribe()
        try:
            while True:
                try:
                    event = q.get(timeout=20)
                except queue.Empty:
                    # heartbeat keepalive
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                if event is _SENTINEL:
                    self.wfile.write(b"event: end\ndata: {}\n\n")
                    self.wfile.flush()
                    break
                line = f"data: {event_json(event)}\n\n".encode()
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


def _try_bind(port: int) -> HTTPServer | None:
    try:
        server = HTTPServer(("127.0.0.1", port), _Handler)
        return server
    except OSError:
        return None


def start_server(port: int = _DEFAULT_PORT, *, open_browser: bool = False) -> int:
    """Start the live server on the given port (auto-increment on conflict).

    Returns the port actually bound. Idempotent: if the server is already
    running, returns the existing port.
    """
    global _server, _server_port
    with _start_lock:
        if _server is not None:
            return _server_port  # type: ignore[return-value]
        server = None
        actual_port = port
        for offset in range(20):
            server = _try_bind(actual_port)
            if server is not None:
                break
            actual_port += 1
        if server is None:
            raise RuntimeError(
                f"Could not bind live server on any port in [{port}, {port + 19}]."
            )
        with _server_lock:
            _server = server
            _server_port = actual_port
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        if open_browser:
            webbrowser.open(f"http://localhost:{actual_port}/")
        return actual_port


def server_url(run_id: str | None = None) -> str | None:
    with _server_lock:
        if _server_port is None:
            return None
        base = f"http://localhost:{_server_port}"
        if run_id:
            return f"{base}/run/{run_id}"
        return base


def is_running() -> bool:
    with _server_lock:
        return _server is not None


def push_event(run_id: str, event: dict[str, Any], *, port: int = _DEFAULT_PORT) -> bool:
    """POST a single event to a remote live server (used by generate process)."""
    import urllib.error
    import urllib.request

    payload = json.dumps({"run_id": run_id, "event": event}, ensure_ascii=False).encode()
    url = f"http://127.0.0.1:{port}/api/push"
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=2):
            return True
    except (urllib.error.URLError, OSError):
        return False
