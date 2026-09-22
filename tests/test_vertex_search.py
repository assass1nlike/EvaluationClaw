import httpx
import pytest

from evalclaw.research import backends


@pytest.mark.parametrize("location,host", [
    ("global", "aiplatform.googleapis.com"),
    ("us-central1", "us-central1-aiplatform.googleapis.com"),
])
def test_vertex_search_uses_oauth_and_preserves_grounding(monkeypatch, location, host):
    monkeypatch.setenv("GEMINI_VERTEX_PROJECT", "test-project")
    monkeypatch.setenv("GEMINI_VERTEX_LOCATION", location)
    monkeypatch.setenv("GEMINI_API_KEY", "unused-developer-key")
    monkeypatch.setattr(backends, "_vertex_auth_headers", lambda: {"Authorization": "Bearer token"})
    calls = []
    monkeypatch.setattr(backends.time, "sleep", lambda _: None)

    def post(client, url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return httpx.Response(503, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "candidates": [{"content": {"parts": [{"text": "grounded answer"}]},
                "groundingMetadata": {"groundingChunks": [
                    {"web": {"uri": "https://example.org/source", "title": "Source"}}
                ]}}],
        })

    monkeypatch.setattr(httpx.Client, "post", post)
    result = backends.web_search("question", backend="auto", resolve_redirects=False, raise_on_error=True)
    assert len(calls) == 2
    assert calls[0] == calls[1]
    url, request = calls[0]
    assert url == (f"https://{host}/v1/projects/test-project/locations/{location}/publishers/"
                   "google/models/gemini-2.5-flash-lite:generateContent")
    assert request["headers"] == {"Content-Type": "application/json", "Authorization": "Bearer token"}
    assert request["json"]["tools"] == [{"googleSearch": {}}]
    assert request["json"]["contents"] == [{"role": "user", "parts": [{"text": "question"}]}]
    assert result.content == "grounded answer"
    assert result.citations == [{"url": "https://example.org/source", "title": "Source"}]


def test_adc_token_is_refreshed_when_expired(monkeypatch):
    pytest.importorskip("google.auth")
    from concurrent.futures import ThreadPoolExecutor

    class Credentials:
        valid = False
        token = None
        refreshes = 0

        def refresh(self, request):
            self.refreshes += 1
            self.token = f"token-{self.refreshes}"
            self.valid = True

    credentials = Credentials()
    monkeypatch.setattr(backends, "_VERTEX_CREDENTIALS", credentials)
    with ThreadPoolExecutor(max_workers=8) as pool:
        headers = list(pool.map(lambda _: backends._vertex_auth_headers(), range(16)))
    assert credentials.refreshes == 1
    assert all(h == {"Authorization": "Bearer token-1"} for h in headers)
    credentials.valid = False
    assert backends._vertex_auth_headers() == {"Authorization": "Bearer token-2"}
    assert credentials.refreshes == 2
