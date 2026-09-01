"""The API is meant to be usable on its own (curl, scripts) via the
auto-generated docs at /docs, without the desktop app or CLI - see
server.py's OPENAPI_TAGS. /docs serves Scalar (get_scalar_api_reference),
not FastAPI's own default Swagger UI (disabled via docs_url=None) - these
pin down that swap alongside the two ways the tagging could quietly rot:
a new route landing with no tag (back to one flat untagged list), or a
tag typo that doesn't match any declared OPENAPI_TAGS entry (still
renders, just outside every documented group)."""

from fastapi.testclient import TestClient

import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_docs_and_openapi_schema_are_served():
    client = _client()
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_serves_scalar_not_swagger_ui():
    r = _client().get("/docs")
    assert "@scalar/api-reference" in r.text
    assert "swagger-ui" not in r.text.lower()


def test_redoc_still_served_as_a_lighter_alternative():
    assert _client().get("/redoc").status_code == 200


def test_openapi_schema_is_the_latest_3_1_version():
    schema = _client().get("/openapi.json").json()
    assert schema["openapi"] == "3.1.0"


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
