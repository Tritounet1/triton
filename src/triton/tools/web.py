"""Reaching outside the local machine: fetching a URL and searching the
web. No API key for either - fetch_url is a plain GET, web_search scrapes
DuckDuckGo's no-JS HTML endpoint (see its bot-detection handling below)."""

import re
from urllib.parse import parse_qs, unquote, urlparse

import requests

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


def web_search(query: str) -> str:
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
                "description": "Searches the web and returns the top result titles and URLs.",
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
