"""Reaching outside the local machine: fetching a URL and searching the
web. fetch_url is a plain GET, no API key. web_search tries Tavily first
(a real search API - actual content snippets, not just a title/link) when
a key is configured, falling back to scraping DuckDuckGo's no-JS HTML
endpoint (no key needed, but brittle - see its own bot-detection handling
below) whenever Tavily is unavailable, most commonly because a free-tier
key ran out of credits."""

import os
import re
from urllib.parse import parse_qs, unquote, urlparse

import requests
from tavily import TavilyClient
from tavily.errors import (
    BadRequestError,
    ForbiddenError,
    InvalidAPIKeyError,
    UsageLimitExceededError,
)
from tavily.errors import TimeoutError as TavilyTimeoutError

from triton.storage.settings import load_tavily_api_key
from triton.tools._shared import Tool


def fetch_url(url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "Triton/1.0"})
        response.raise_for_status()
    except requests.RequestException as e:
        return f"error: could not fetch {url} ({e})"

    text = response.text
    if "html" in response.headers.get("content-type", ""):
        text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()

    if len(text) > 5000:
        text = text[:5000] + "\n(truncated)"
    return text


def _effective_tavily_key() -> str | None:
    return load_tavily_api_key() or os.getenv("TAVILY_API_KEY")


def is_tavily_configured() -> bool:
    """Whether web_search will try Tavily at all (Settings UI key or
    TAVILY_API_KEY env var) - unlike is_api_key_configured() (api.py),
    False here isn't fatal, it just means every search goes straight to
    the DuckDuckGo fallback. Used by server.py's GET /settings/tavily_key
    to show the same configured/not-configured badge the OpenRouter key
    already gets."""
    return _effective_tavily_key() is not None


def _tavily_search(query: str, api_key: str) -> str | None:
    """None means "unavailable right now" - web_search falls back to
    _duckduckgo_search below rather than surfacing this as a hard error,
    since that free fallback already exists. Never raises: a free-tier
    Tavily key running out of credits (UsageLimitExceededError) is the
    most likely case day to day, but any failure here degrades the same
    way rather than taking web_search down entirely."""
    try:
        response = TavilyClient(api_key=api_key).search(query, max_results=8)
    except (
        UsageLimitExceededError,
        InvalidAPIKeyError,
        ForbiddenError,
        BadRequestError,
        TavilyTimeoutError,
        requests.RequestException,
    ):
        return None

    results = response.get("results") or []
    if not results:
        return None
    lines = [
        f"{r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}".strip() for r in results
    ]
    return "\n\n".join(lines)


def _duckduckgo_search(query: str) -> str:
    # scrapes DuckDuckGo's no-JS HTML endpoint (no API key required); the
    # regex parsing is brittle to markup changes but keeps this dependency-free
    try:
        response = requests.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; Triton/1.0)"},
        )
        response.raise_for_status()
    except requests.RequestException as e:
        return f"error: web search failed ({e})"

    if "anomaly-modal" in response.text:
        # retrying web_search itself almost never helps - it's the same
        # anti-bot wall, not a transient blip - so this steers straight to
        # the fallback that actually works instead of wasting a turn on a
        # second web_search call first (confirmed in real use: fetch_url on
        # an official/specialized site directly gets through every time).
        return (
            "error: DuckDuckGo blocked this search with a bot-detection challenge. "
            "Retrying web_search won't help, it's not transient - use fetch_url "
            "directly on a specific site likely to have the answer instead "
            "(an official source, a well-known specialized site for the topic, "
            "or a Wikipedia page)."
        )

    raw_results = re.findall(
        r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        response.text,
        flags=re.DOTALL,
    )
    if not raw_results:
        return "(no results)"

    lines: list[str] = []
    for href, title in raw_results[:8]:
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        target_url = parse_qs(urlparse(href).query).get("uddg", [href])[0]
        lines.append(f"{clean_title}\n{unquote(target_url)}")
    return "\n\n".join(lines)


def web_search(query: str) -> str:
    api_key = _effective_tavily_key()
    if api_key:
        result = _tavily_search(query, api_key)
        if result is not None:
            return f"[source: Tavily]\n\n{result}"
    # tagged the same way even on an error string (e.g. DuckDuckGo's own
    # bot-detection message) - the desktop app strips this line for
    # display and turns it into a small "Tavily"/"DuckDuckGo" pill next to
    # the call instead (see webSearchSource() in App.tsx), so which
    # backend actually answered is visible without expanding the call.
    return f"[source: DuckDuckGo]\n\n{_duckduckgo_search(query)}"


REGISTRY: dict[str, Tool] = {
    "fetch_url": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "fetch_url",
                "description": "Fetches a URL and returns its text content "
                "(HTML tags stripped for web pages).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "URL to fetch (must start with http:// or https://).",
                        },
                    },
                    "required": ["url"],
                },
            },
        },
        fn=fetch_url,
        read_only=True,
    ),
    "web_search": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Searches the web and returns the top results (title, URL, and "
                "a content snippet when available).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query.",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        fn=web_search,
        read_only=True,
    ),
}
