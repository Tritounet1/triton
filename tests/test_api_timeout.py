"""The OpenRouter client must bound stalled upstream requests explicitly."""

from triton.llm import api


def test_openrouter_client_uses_the_explicit_request_timeout(monkeypatch):
    captured: dict[str, object] = {}

    def fake_openai(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(api, "OpenAI", fake_openai)
    monkeypatch.setattr(api, "_effective_api_key", lambda: "test-key")

    api._client()

    assert captured["timeout"] == api.OPENROUTER_REQUEST_TIMEOUT_SECONDS
    assert captured["max_retries"] == 0
