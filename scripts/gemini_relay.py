"""Round-robin Gemini API-key relay with 429 backoff.

Spreads Gemini ``generateContent`` requests across N API keys (each key lives in
its own Google Cloud project, so each carries its own quota pool). On a 429 the
request is retried against the next key with exponential backoff.

Point EvalClaw at this relay instead of Google directly::

    GEMINI_API_BASE=http://127.0.0.1:<port>/v1beta \
    GEMINI_API_KEY=ignored \
    evalclaw generate ...

The relay replaces ``x-goog-api-key`` with the next key in its pool, so the
``GEMINI_API_KEY`` value the framework sends is not used.

Usage::

    python scripts/gemini_relay.py --keys KEY1,KEY2,KEY3 [--port 9000]
    python scripts/gemini_relay.py --keys-file keys.txt [--port 9000] \
        --proxy http://127.0.0.1:7890
"""
from __future__ import annotations

import argparse
import asyncio

import aiohttp
from aiohttp import web

UPSTREAM = "https://generativelanguage.googleapis.com"


class KeyPool:
    """Rotate across keys. ``next`` is called without an intervening await, so
    it is atomic on aiohttp's single event loop and safe across requests."""

    def __init__(self, keys: list[str]) -> None:
        self.keys = keys
        self.index = 0

    def next(self) -> str:
        key = self.keys[self.index % len(self.keys)]
        self.index += 1
        return key


def _load_keys(keys_arg: str | None, keys_file: str | None) -> list[str]:
    keys: list[str] = []
    if keys_arg:
        keys.extend(part.strip() for part in keys_arg.split(",") if part.strip())
    if keys_file:
        with open(keys_file, encoding="utf-8") as handle:
            keys.extend(line.strip() for line in handle if line.strip())
    if not keys:
        raise SystemExit("No API keys given; pass --keys or --keys-file.")
    return list(dict.fromkeys(keys))


async def _backoff(attempt: int) -> None:
    await asyncio.sleep(min(2.0**attempt, 30.0))


async def _forward(session: aiohttp.ClientSession, pool: KeyPool, path: str, body: bytes) -> web.Response:
    for attempt in range(len(pool.keys) * 3):
        key = pool.next()
        async with session.post(
            UPSTREAM + path,
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            data=body,
        ) as response:
            if response.status != 429:
                content_type = (response.headers.get("Content-Type") or "application/json").split(";", 1)[0].strip()
                return web.Response(
                    status=response.status,
                    body=await response.read(),
                    content_type=content_type,
                )
        await _backoff(attempt)
    return web.Response(status=429, text="all Gemini keys are rate-limited")


async def _handle(request: web.Request) -> web.Response:
    body = await request.read()
    return await _forward(request.app["session"], request.app["pool"], request.path, body)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keys", help="Comma-separated Gemini API keys.")
    parser.add_argument("--keys-file", help="Path to a file with one key per line.")
    parser.add_argument("--port", type=int, default=9000)
    parser.add_argument("--proxy", help="Proxy URL for upstream requests, e.g. http://127.0.0.1:7890")
    args = parser.parse_args()

    app = web.Application()
    app["pool"] = KeyPool(_load_keys(args.keys, args.keys_file))
    app["proxy"] = args.proxy

    async def on_startup(app: web.Application) -> None:
        app["session"] = aiohttp.ClientSession(
            trust_env=True,
            proxy=app["proxy"],
            timeout=aiohttp.ClientTimeout(total=30),
        )

    async def on_cleanup(app: web.Application) -> None:
        await app["session"].close()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.router.add_get("/health", lambda _request: web.Response(text="ok"))
    app.router.add_post("/{tail:.*}", _handle)

    web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
