"""Model API egress gateway: a strict reverse proxy to a single upstream host.

The harness container runs on an internal Docker network with no external
egress and points its model base_url at this gateway. The gateway forwards only
to the configured upstream (the model API), so the agent can reach the model
and nothing else.

Usage::

    python -m evalclaw.execution.model_gateway --upstream https://api.deepseek.com --port 18080
"""

from __future__ import annotations

import argparse
import asyncio
import codecs
import json
import os
import time
import uuid
from collections.abc import Mapping
from pathlib import Path

import aiohttp
from aiohttp import web

_STRIP_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "authorization",
    "x-api-key",
    "proxy-authorization",
}
_STRIP_RESPONSE_HEADERS = {"transfer-encoding", "connection", "content-encoding", "content-length"}
_ALLOWED_PATHS = {
    "/chat/completions",
    "/responses",
    "/messages",
    "/messages/count_tokens",
    "/v1/chat/completions",
    "/v1/responses",
    "/v1/messages",
    "/v1/messages/count_tokens",
}


def _record(app, event: dict) -> None:
    path = app.get("evidence_path")
    if path:
        with Path(path).open("a", encoding="utf-8") as output:
            output.write(json.dumps({"time": time.time(), **event}, ensure_ascii=False) + "\n")


def _upstream_headers(
    request_headers: Mapping[str, str], provider: str, api_key: str
) -> dict[str, str]:
    headers = {
        key: value
        for key, value in request_headers.items()
        if key.lower() not in _STRIP_REQUEST_HEADERS
    }
    if provider == "anthropic":
        headers["x-api-key"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _validate_model(body: bytes, expected_model: str) -> None:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise web.HTTPBadRequest(reason="Model API requests must contain JSON.") from exc
    if not isinstance(payload, dict) or payload.get("model") != expected_model:
        raise web.HTTPForbidden(reason="The gateway permits only the configured model.")


def _configured_body(body: bytes, model: str, extra_body: dict) -> bytes:
    _validate_model(body, model)
    payload = json.loads(body)
    payload.update(extra_body)
    result = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    _validate_model(result, model)
    return result


async def _forward(request: web.Request) -> web.StreamResponse:
    if request.method != "POST":
        raise web.HTTPMethodNotAllowed(request.method, ["POST"])
    if request.path not in _ALLOWED_PATHS:
        raise web.HTTPNotFound()
    upstream = request.app["upstream"]
    body = _configured_body(
        await request.read(), request.app["model"], request.app.get("extra_body", {})
    )
    api_key = request.app["api_key"]
    headers = _upstream_headers(request.headers, request.app["provider"], api_key)
    request_id = uuid.uuid4().hex
    _record(
        request.app,
        {"kind": "request", "id": request_id, "path": request.path, "payload": json.loads(body)},
    )
    # Heartbeats indicate a live provider request. The owning episode enforces
    # its wall-clock budget; a fixed 300s gateway total truncated healthy waits.
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=300)
    ) as session:
        for attempt in range(8):
            try:
                response = await session.request(
                    request.method,
                    upstream + request.path_qs,
                    headers=headers,
                    data=body,
                )
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                _record(
                    request.app,
                    {
                        "kind": "upstream_error",
                        "id": request_id,
                        "attempt": attempt + 1,
                        "error": type(exc).__name__,
                    },
                )
                if attempt == 7:
                    raise web.HTTPBadGateway(reason="Model upstream connection failed") from exc
                await asyncio.sleep(min(5 * 2**attempt, 60))
                continue
            if response.status in {408, 429, 500, 502, 503, 504} and attempt < 7:
                _record(
                    request.app,
                    {
                        "kind": "upstream_retry",
                        "id": request_id,
                        "attempt": attempt + 1,
                        "status": response.status,
                    },
                )
                response.release()
                await asyncio.sleep(min(5 * 2**attempt, 60))
                continue
            async with response:
                # aiohttp already decompresses the body, so drop the encoding header.
                out_headers = {
                    key: value
                    for key, value in response.headers.items()
                    if key.lower() not in _STRIP_RESPONSE_HEADERS
                }
                out = web.StreamResponse(status=response.status, headers=out_headers)
                _record(
                    request.app,
                    {"kind": "response_start", "id": request_id, "status": response.status},
                )
                await out.prepare(request)
                decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
                complete = False
                try:
                    async for chunk in response.content.iter_any():
                        _record(
                            request.app,
                            {
                                "kind": "response_chunk",
                                "id": request_id,
                                "body": decoder.decode(chunk),
                            },
                        )
                        await out.write(chunk)
                    await out.write_eof()
                    complete = True
                finally:
                    _record(
                        request.app,
                        {
                            "kind": "response_end",
                            "id": request_id,
                            "complete": complete,
                            "body": decoder.decode(b"", final=True),
                        },
                    )
                return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--upstream", required=True, help="Model API base URL, e.g. https://api.deepseek.com"
    )
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--evidence-path", default="/tmp/model-events.jsonl")
    args = parser.parse_args()

    app = web.Application()
    app["upstream"] = args.upstream.rstrip("/")
    app["provider"] = args.provider
    app["model"] = args.model
    app["api_key"] = os.environ["EVALCLAW_UPSTREAM_API_KEY"]
    app["extra_body"] = json.loads(os.environ.get("EVALCLAW_UPSTREAM_EXTRA_BODY", "{}"))
    if not isinstance(app["extra_body"], dict):
        raise ValueError("EVALCLAW_UPSTREAM_EXTRA_BODY must be a JSON object.")
    app["evidence_path"] = args.evidence_path
    app.router.add_route("*", "/{tail:.*}", _forward)

    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
