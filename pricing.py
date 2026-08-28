"""Caches OpenRouter's per-model pricing (refreshed periodically) so token
counts logged for a call can be converted to an actual dollar cost, without
hitting the network on every single model call just to look up a price."""

import time

import requests

CACHE_TTL_SECONDS = 3600

_cache: dict[str, tuple[float, float]] = {}
_cache_time = 0.0


def _refresh() -> None:
    global _cache, _cache_time
    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        # keep serving the last known prices (or an empty cache) rather than
        # let a pricing lookup failure interrupt a chat turn
        return

    prices: dict[str, tuple[float, float]] = {}
    for m in resp.json().get("data", []):
        pricing = m.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt", 0))
            completion_price = float(pricing.get("completion", 0))
        except (TypeError, ValueError):
            continue
        prices[m["id"]] = (prompt_price, completion_price)

    _cache = prices
    _cache_time = time.monotonic()


def get_price(model_id: str) -> tuple[float, float] | None:
    """Returns (prompt_price_per_token, completion_price_per_token) in USD
    for a model, or None if unknown. Refreshes the cache when stale."""
    if time.monotonic() - _cache_time > CACHE_TTL_SECONDS:
        _refresh()
    return _cache.get(model_id)


def estimate_cost(model_id: str, prompt_tokens: int, completion_tokens: int) -> float | None:
    """Returns the estimated cost in USD for a call, or None if the
    model's pricing is unknown (so callers can tell "cost was zero" apart
    from "cost is unknown")."""
    price = get_price(model_id)
    if price is None:
        return None
    prompt_price, completion_price = price
    return prompt_tokens * prompt_price + completion_tokens * completion_price
