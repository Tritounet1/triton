import pytest

from triton.web_runtime import SlidingWindowRateLimiter, WebRuntimeConfig, load_web_runtime_config


def test_rate_limiter_releases_requests_after_its_window():
    limiter = SlidingWindowRateLimiter(
        WebRuntimeConfig(max_request_bytes=1, rate_limit_requests=2, rate_limit_window_seconds=10)
    )

    assert limiter.retry_after_seconds("client", now=0) == 0
    assert limiter.retry_after_seconds("client", now=1) == 0
    assert limiter.retry_after_seconds("client", now=2) == 8
    assert limiter.retry_after_seconds("client", now=10) == 0


def test_runtime_configuration_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("TRITON_WEB_RATE_LIMIT_REQUESTS", "zero")

    with pytest.raises(ValueError, match="TRITON_WEB_RATE_LIMIT_REQUESTS"):
        load_web_runtime_config()
