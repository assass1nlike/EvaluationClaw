import asyncio
import json

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

import scripts.gemini_relay as relay


async def _no_backoff(_attempt: int) -> None:
    return None


def _mock_upstream() -> tuple[web.Application, list[str]]:
    seen: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        key = request.headers.get("x-goog-api-key", "")
        seen.append(key)
        if len(seen) == 1:
            return web.Response(status=429, text="rate limited")
        return web.Response(
            status=200,
            text=json.dumps({"answer": key}),
            content_type="application/json",
        )

    app = web.Application()
    app.router.add_post("/v1beta/models/m:generateContent", handler)
    return app, seen


async def _run_forward(upstream_app: web.Application, keys: list[str], monkeypatch) -> web.Response:
    server = TestServer(upstream_app)
    await server.start_server()
    monkeypatch.setattr(relay, "UPSTREAM", str(server.make_url("/")).rstrip("/"))
    monkeypatch.setattr(relay, "_backoff", _no_backoff)
    session = aiohttp.ClientSession()
    try:
        return await relay._forward(
            session,
            relay.KeyPool(keys),
            "/v1beta/models/m:generateContent",
            b'{"q": 1}',
        )
    finally:
        await session.close()
        await server.close()


def test_relay_round_robins_keys_and_retries_on_429(monkeypatch) -> None:
    upstream_app, seen = _mock_upstream()

    response = asyncio.run(_run_forward(upstream_app, ["key1", "key2"], monkeypatch))

    assert response.status == 200
    assert json.loads(response.body) == {"answer": "key2"}
    assert seen == ["key1", "key2"]


def test_relay_returns_429_when_every_key_is_rate_limited(monkeypatch) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=429, text="rate limited")

    app = web.Application()
    app.router.add_post("/v1beta/models/m:generateContent", handler)

    response = asyncio.run(_run_forward(app, ["key1"], monkeypatch))

    assert response.status == 429
