"""The API is meant to be usable on its own (curl, scripts) via the
auto-generated Swagger UI at /docs, without the desktop app or CLI - see
server.py's OPENAPI_TAGS. These pin down the two ways that could quietly
rot: a new route landing with no tag (back to one flat untagged list), or
a tag typo that doesn't match any declared OPENAPI_TAGS entry (Swagger UI
would still render it, just outside every documented group)."""

from fastapi.testclient import TestClient

import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_docs_and_openapi_schema_are_served():
    client = _client()
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_root_redirects_to_docs():
    client = _client()
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/docs"


def test_every_route_has_at_least_one_tag():
    schema = _client().get("/openapi.json").json()
    untagged = [
        f"{method.upper()} {path}"
        for path, methods in schema["paths"].items()
        for method, op in methods.items()
        if not op.get("tags")
    ]
    assert untagged == []


def test_every_used_tag_is_declared_in_openapi_tags():
    schema = _client().get("/openapi.json").json()
    declared = {t["name"] for t in schema.get("tags", [])}
    used = {
        tag
        for methods in schema["paths"].values()
        for op in methods.values()
        for tag in op.get("tags", [])
    }
    assert used <= declared
