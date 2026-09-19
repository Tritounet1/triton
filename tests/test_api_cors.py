"""The local API must only be callable from Triton's own WebView/dev UI.

Binding Uvicorn to 127.0.0.1 does not stop a malicious web page from making
browser requests to it, so wildcard CORS would expose local conversations and
project files to any site the user visits.
"""

from fastapi.testclient import TestClient

import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_cors_allows_the_vite_development_ui():
    response = _client().options(
        "/sessions",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:1420"


def test_cors_allows_the_tauri_production_webview():
    response = _client().options(
        "/sessions",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_cors_rejects_an_untrusted_website():
    response = _client().options(
        "/sessions",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_sidecar_token_rejects_requests_without_the_matching_header(monkeypatch):
    monkeypatch.setattr(server, "LOCAL_API_TOKEN", "sidecar-secret")

    client = _client()
    denied = client.get("/health")
    accepted = client.get("/health", headers={server.LOCAL_API_TOKEN_HEADER: "sidecar-secret"})
    preflight = client.options(
        "/health",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": server.LOCAL_API_TOKEN_HEADER,
        },
    )

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert preflight.status_code == 200
