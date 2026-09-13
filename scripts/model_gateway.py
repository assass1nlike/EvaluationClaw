"""Model API egress gateway: a strict reverse proxy to a single upstream host.

The harness container runs on an internal Docker network with no external
egress and points its model base_url at this gateway. The gateway forwards only
to the configured upstream (the model API), so the agent can reach the model
and nothing else.

Usage::

    python scripts/model_gateway.py --upstream https://api.deepseek.com --port 18080
"""
from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping

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


async def _forward(request: web.Request) -> web.StreamResponse:
    if request.method != "POST":
        raise web.HTTPMethodNotAllowed(request.method, ["POST"])
    if request.path not in _ALLOWED_PATHS:
        raise web.HTTPNotFound()
    upstream = request.app["upstream"]
    body = await request.read()
    _validate_model(body, request.app["model"])
    api_key = request.app["api_key"]
    headers = _upstream_headers(request.headers, request.app["provider"], api_key)
    async with aiohttp.ClientSession() as session:
        async with session.request(
            request.method,
            upstream + request.path_qs,
            headers=headers,
            data=body,
            timeout=aiohttp.ClientTimeout(total=300, sock_connect=30),
        ) as response:
            # aiohttp already decompresses the body, so drop the encoding header.
            out_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in _STRIP_RESPONSE_HEADERS
            }
            out = web.StreamResponse(status=response.status, headers=out_headers)
            await out.prepare(request)
            async for chunk in response.content.iter_any():
                await out.write(chunk)
            await out.write_eof()
            return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", required=True, help="Model API base URL, e.g. https://api.deepseek.com")
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    app = web.Application()
    app["upstream"] = args.upstream.rstrip("/")
    app["provider"] = args.provider
    app["model"] = args.model
    app["api_key"] = os.environ["EVALCLAW_UPSTREAM_API_KEY"]
    app.router.add_route("*", "/{tail:.*}", _forward)

    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
