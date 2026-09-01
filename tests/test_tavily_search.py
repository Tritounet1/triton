"""web_search now tries Tavily first (a real search API - content
snippets, not just links) when a key is configured, falling back to the
existing DuckDuckGo scrape otherwise or whenever Tavily itself fails -
most commonly a free-tier key running out of credits
(UsageLimitExceededError). No real network access here: TavilyClient and
requests.get are both faked."""

from types import SimpleNamespace

import pytest
from tavily.errors import InvalidAPIKeyError, UsageLimitExceededError

from triton.storage import settings
from triton.tools import web


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    # a real TAVILY_API_KEY may be set in this machine's own .env (loaded
    # by main.py/server.py at their own startup, not by pytest) - cleared
    # so "no key configured" tests aren't at the mercy of that.
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def _duckduckgo_response(html: str):
    return SimpleNamespace(text=html, raise_for_status=lambda: None)


# --- _effective_tavily_key ---


def test_effective_tavily_key_prefers_settings_over_env(monkeypatch):
    settings.save_tavily_api_key("from-settings")
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")
    assert web._effective_tavily_key() == "from-settings"


def test_effective_tavily_key_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")
    assert web._effective_tavily_key() == "from-env"


def test_effective_tavily_key_none_when_neither_set():
    assert web._effective_tavily_key() is None


def test_is_tavily_configured_matches_effective_key(monkeypatch):
    assert web.is_tavily_configured() is False
    monkeypatch.setenv("TAVILY_API_KEY", "from-env")
    assert web.is_tavily_configured() is True


# --- _tavily_search ---


def test_tavily_search_formats_title_url_content(monkeypatch):
    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def search(self, query, max_results=8):
            return {
                "results": [
                    {"title": "Result A", "url": "https://a.example", "content": "About A"},
                    {"title": "Result B", "url": "https://b.example", "content": "About B"},
                ]
            }

    monkeypatch.setattr(web, "TavilyClient", FakeClient)

    result = web._tavily_search("query", "tvly-xxx", 8)

    assert result == "Result A\nhttps://a.example\nAbout A\n\nResult B\nhttps://b.example\nAbout B"


def test_tavily_search_passes_max_results_through_to_the_client(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=8):
            captured["max_results"] = max_results
            return {"results": []}

    monkeypatch.setattr(web, "TavilyClient", FakeClient)
    web._tavily_search("query", "tvly-xxx", 15)

    assert captured["max_results"] == 15


def test_tavily_search_returns_none_on_empty_results(monkeypatch):
    class FakeClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=8):
            return {"results": []}

    monkeypatch.setattr(web, "TavilyClient", FakeClient)
    assert web._tavily_search("query", "tvly-xxx", 8) is None


@pytest.mark.parametrize(
    "exc",
    [
        UsageLimitExceededError("out of credits"),
        InvalidAPIKeyError("bad key"),
    ],
)
def test_tavily_search_returns_none_instead_of_raising(monkeypatch, exc):
    class FakeClient:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results=8):
            raise exc

    monkeypatch.setattr(web, "TavilyClient", FakeClient)
    assert web._tavily_search("query", "tvly-xxx", 8) is None


# --- web_search: which path it takes, and max_results handling ---


def test_web_search_uses_tavily_when_configured_and_available(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-xxx")
    monkeypatch.setattr(web, "_tavily_search", lambda query, api_key, max_results: "tavily result")
    monkeypatch.setattr(
        web,
        "_duckduckgo_search",
        lambda query, max_results: (_ for _ in ()).throw(
            AssertionError("must not fall back to DuckDuckGo")
        ),
    )

    # tagged with its source (see webSearchSource() in App.tsx, which
    # strips this same marker for display and turns it into a pill badge)
    assert web.web_search("query") == "[source: Tavily]\n\ntavily result"


def test_web_search_falls_back_to_duckduckgo_when_tavily_unavailable(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-xxx")
    monkeypatch.setattr(web, "_tavily_search", lambda query, api_key, max_results: None)
    monkeypatch.setattr(web, "_duckduckgo_search", lambda query, max_results: "duckduckgo result")

    assert web.web_search("query") == "[source: DuckDuckGo]\n\nduckduckgo result"


def test_web_search_skips_tavily_entirely_without_a_key(monkeypatch):
    # no TAVILY_API_KEY set (cleared by the autouse fixture) - _tavily_search
    # must never even be called, not just return None
    monkeypatch.setattr(
        web,
        "_tavily_search",
        lambda query, api_key, max_results: (_ for _ in ()).throw(
            AssertionError("must not call Tavily at all")
        ),
    )
    monkeypatch.setattr(web, "_duckduckgo_search", lambda query, max_results: "duckduckgo result")

    assert web.web_search("query") == "[source: DuckDuckGo]\n\nduckduckgo result"


def test_web_search_default_max_results_is_8(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        web,
        "_duckduckgo_search",
        lambda query, max_results: captured.setdefault("max_results", max_results) and "r",
    )
    web.web_search("query")
    assert captured["max_results"] == 8


def test_web_search_passes_a_custom_max_results_through(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        web,
        "_duckduckgo_search",
        lambda query, max_results: captured.setdefault("max_results", max_results) and "r",
    )
    web.web_search("query", max_results=3)
    assert captured["max_results"] == 3


def test_web_search_clamps_an_unreasonably_high_max_results(monkeypatch):
    """Defends against a hallucinated value (e.g. the model passing 500) -
    Tavily itself doesn't error past MAX_MAX_RESULTS, it just quietly
    returns fewer results than asked (verified live), so this clamp is
    purely to keep a single call's context/cost bounded."""
    captured = {}
    monkeypatch.setattr(
        web,
        "_duckduckgo_search",
        lambda query, max_results: captured.setdefault("max_results", max_results) and "r",
    )
    web.web_search("query", max_results=500)
    assert captured["max_results"] == web.MAX_MAX_RESULTS


def test_web_search_duckduckgo_path_still_works_end_to_end(monkeypatch):
    """No mocking of _duckduckgo_search itself here - exercises the real
    regex parsing against a fake HTML response, pinning down that the
    pre-existing scrape (kept as the fallback, per the request) wasn't
    broken by this change."""
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">'
        "Example Title</a>"
    )
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _duckduckgo_response(html))

    result = web._duckduckgo_search("query", 8)

    assert result == "Example Title\nhttps://example.com"
