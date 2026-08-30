"""/openrouter/models used to hit OpenRouter's real API on every single
call - the desktop app's own startup and every reopen of Settings > Modele
each cost a fresh round-trip. These pin down the cache-with-TTL behavior
that fixed it (mirrors pricing.py's get_price(), same shape), with
requests.get monkeypatched so no network call happens."""

from types import SimpleNamespace

import pytest
import requests

import server


@pytest.fixture(autouse=True)
def _reset_cache():
    """Each test starts from a clean slate - these are module-level
    globals that would otherwise leak state between tests."""
    server._models_cache = None
    server._models_cache_time = 0.0
    yield
    server._models_cache = None
    server._models_cache_time = 0.0


def _fake_openrouter_response(model_id: str = "test/model"):
    return SimpleNamespace(
        raise_for_status=lambda: None,
        json=lambda: {
            "data": [
                {
                    "id": model_id,
                    "name": "Test Model",
                    "context_length": 128000,
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text", "image"]},
                }
            ]
        },
    )


def test_first_call_hits_the_network_and_populates_the_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: (calls.append(1), _fake_openrouter_response())[1]
    )

    models = server.list_openrouter_models()

    assert len(calls) == 1
    assert models == [
        {
            "id": "test/model",
            "name": "Test Model",
            "context_length": 128000,
            "prompt_price": 1.0,
            "completion_price": 2.0,
            "supports_tools": True,
            "supports_images": True,
            "supports_files": False,
        }
    ]
    assert server._models_cache == models


def test_second_call_within_ttl_serves_the_cache_no_network_call(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: (calls.append(1), _fake_openrouter_response())[1]
    )

    first = server.list_openrouter_models()
    second = server.list_openrouter_models()

    assert len(calls) == 1
    assert first == second


def test_cache_is_refetched_once_the_ttl_expires(monkeypatch):
    calls = []
    monkeypatch.setattr(
        requests, "get", lambda *a, **k: (calls.append(1), _fake_openrouter_response())[1]
    )

    server.list_openrouter_models()
    # simulate the TTL having elapsed, without an actual sleep
    server._models_cache_time -= server._MODELS_CACHE_TTL_SECONDS + 1
    server.list_openrouter_models()

    assert len(calls) == 2


def test_network_failure_serves_the_stale_cache_instead_of_erroring(monkeypatch):
    monkeypatch.setattr(requests, "get", lambda *a, **k: _fake_openrouter_response())
    first = server.list_openrouter_models()

    # cache now expired and OpenRouter unreachable
    server._models_cache_time -= server._MODELS_CACHE_TTL_SECONDS + 1

    def _boom(*_a: object, **_k: object):
        raise requests.RequestException("network is down")

    monkeypatch.setattr(requests, "get", _boom)

    second = server.list_openrouter_models()
    assert second == first


def test_network_failure_with_no_cache_yet_raises(monkeypatch):
    def _boom(*_a: object, **_k: object):
        raise requests.RequestException("network is down")

    monkeypatch.setattr(requests, "get", _boom)

    with pytest.raises(Exception, match="could not reach OpenRouter"):
        server.list_openrouter_models()
