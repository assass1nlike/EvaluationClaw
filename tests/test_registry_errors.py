import httpx
import pytest

from evalclaw.execution import registry_errors as registry


@pytest.mark.parametrize("status,body,kind,codes", [
    (404, {"errors": [{"code": "MANIFEST_UNKNOWN"}]}, "reference", ["MANIFEST_UNKNOWN"]),
    (400, {"errors": [{"code": "NAME_INVALID"}]}, "reference", ["NAME_INVALID"]),
    (404, "MANIFEST_UNKNOWN: mirror page not found", "unknown", []),
    (404, {"errors": [{"message": "MANIFEST_UNKNOWN"}]}, "unknown", []),
    (404, {"errors": [{"code": "MANIFEST_UNKNOWN"}, {"code": "UNKNOWN"}]}, "unknown", ["MANIFEST_UNKNOWN", "UNKNOWN"]),
    (503, {"errors": [{"code": "MANIFEST_UNKNOWN"}]}, "service", ["MANIFEST_UNKNOWN"]),
    (429, "rate limited", "service", []),
    (401, {"errors": [{"code": "UNAUTHORIZED"}]}, "permission", ["UNAUTHORIZED"]),
    (200, {"schemaVersion": 2}, "unknown", []),
])
def test_protocol_codes_not_text_determine_reference_errors(monkeypatch, status, body, kind, codes):
    def handle(request):
        assert request.url == "https://mirror.example/v2/team/image/manifests/missing"
        return httpx.Response(status, **({"json": body} if isinstance(body, dict) else {"text": body}))
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(registry.httpx, "Client", lambda **kwargs: client)
    result = registry.inspect_registry_failure("mirror.example/team/image:missing", {}, 5)
    assert result == {"source": "mirror.example/team/image:missing", "kind": kind, "status": status, "codes": codes}


def test_bearer_challenge_before_missing_manifest(monkeypatch):
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.host == "auth.example":
            assert request.url.params["scope"] == "repository:team/image:pull"
            return httpx.Response(200, json={"access_token": "test-token"})
        if "authorization" not in request.headers:
            return httpx.Response(401, headers={"WWW-Authenticate":
                'Bearer realm="https://auth.example/token",service="registry",scope="repository:team/image:pull"'})
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(404, json={"errors": [{"code": "MANIFEST_UNKNOWN"}]})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(registry.httpx, "Client", lambda **kwargs: client)
    result = registry.inspect_registry_failure("mirror.example/team/image:missing", {}, 5)
    assert result["kind"] == "reference"
    assert len(calls) == 3
    assert "test-token" not in str(result)


@pytest.mark.parametrize("status,body,kind", [
    (503, "unavailable", "service"),
    (429, "limited", "service"),
    (404, {"errors": [{"code": "MANIFEST_UNKNOWN"}]}, "unknown"),
    (200, {}, "unknown"),
])
def test_token_service_failure_does_not_imply_bad_image(monkeypatch, status, body, kind):
    def handle(request):
        if request.url.host == "auth.example":
            return httpx.Response(status, **({"json": body} if isinstance(body, dict) else {"text": body}))
        return httpx.Response(401, headers={"WWW-Authenticate": 'Bearer realm="https://auth.example/token"'})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(registry.httpx, "Client", lambda **kwargs: client)
    assert registry.inspect_registry_failure("mirror.example/image:tag", {}, 5)["kind"] == kind


@pytest.mark.parametrize("error,kind", [(httpx.ConnectError, "network"), (httpx.ReadTimeout, "timeout")])
def test_transport_errors_are_not_reference_errors(monkeypatch, error, kind):
    def handle(request):
        raise error("unavailable", request=request)
    client = httpx.Client(transport=httpx.MockTransport(handle))
    monkeypatch.setattr(registry.httpx, "Client", lambda **kwargs: client)
    assert registry.inspect_registry_failure("mirror.example/image:tag", {}, 5)["kind"] == kind
