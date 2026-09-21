"""Read registry protocol errors after a failed image transfer."""

from __future__ import annotations

from urllib.parse import quote, urlsplit
from urllib.request import parse_http_list, parse_keqv_list

import httpx


def inspect_registry_failure(source: str, env: dict[str, str], timeout_s: float) -> dict:
    """Anonymous diagnostic only; crane remains responsible for authenticated pulls.

    A failed anonymous diagnostic cannot establish that a private image is absent.
    Only explicit registry error codes establish a reference problem. HTML 404s,
    proxy failures, and successful manifest lookups remain unclassified.
    """
    host, repository = source.split("/", 1)
    if "@" in repository:
        repository, reference = repository.rsplit("@", 1)
    elif ":" in repository.rsplit("/", 1)[-1]:
        repository, reference = repository.rsplit(":", 1)
    else:
        reference = "latest"
    url = f"https://{host}/v2/{quote(repository, safe='/')}/manifests/{quote(reference, safe=':')}"
    headers = {"Accept": ", ".join([
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ])}
    result = {"source": source, "kind": "unknown", "status": None, "codes": []}
    # image_source_env only changes the proxy route relative to os.environ.
    trust_env = any(key.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"} for key in env)
    try:
        with httpx.Client(timeout=min(timeout_s, 30), trust_env=trust_env, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            manifest_lookup = True
            scheme, _, challenge = response.headers.get("www-authenticate", "").partition(" ")
            if response.status_code == 401 and scheme.lower() == "bearer":
                fields = parse_keqv_list(parse_http_list(challenge))
                realm = fields.get("realm", "")
                parsed = urlsplit(realm)
                if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password:
                    token_response = client.get(realm, params={
                        key: fields[key] for key in ("service", "scope") if key in fields
                    })
                    if token_response.is_success:
                        payload = token_response.json()
                        token = (payload.get("token") or payload.get("access_token")) if isinstance(payload, dict) else None
                        if isinstance(token, str) and token:
                            response = client.get(url, headers={**headers, "Authorization": f"Bearer {token}"})
                        else:
                            return result
                    else:
                        response = token_response
                        manifest_lookup = False
            result["status"] = response.status_code
            if response.status_code in {401, 403}:
                result["kind"] = "permission"
            elif response.status_code == 429 or response.status_code >= 500:
                result["kind"] = "service"
            payload = response.json()
            errors = payload.get("errors", []) if isinstance(payload, dict) else []
            if isinstance(errors, list):
                result["codes"] = [e["code"] for e in errors
                                   if isinstance(e, dict) and isinstance(e.get("code"), str)]
            codes = set(result["codes"])
            if manifest_lookup and response.status_code in {400, 404} and codes and codes <= {
                "MANIFEST_UNKNOWN", "NAME_UNKNOWN", "NAME_INVALID", "TAG_INVALID", "DIGEST_INVALID",
            }:
                result["kind"] = "reference"
    except httpx.TimeoutException:
        result["kind"] = "timeout"
    except httpx.TransportError:
        result["kind"] = "network"
    except (ValueError, httpx.HTTPError):
        pass
    return result
