from collections import deque
from dataclasses import dataclass, field
from os import getenv
from threading import Lock
from time import monotonic


def _positive_environment_integer(name: str, default: int) -> int:
    raw = getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class WebRuntimeConfig:
    max_request_bytes: int
    rate_limit_requests: int
    rate_limit_window_seconds: int


def load_web_runtime_config() -> WebRuntimeConfig:
    return WebRuntimeConfig(
        max_request_bytes=_positive_environment_integer(
            "TRITON_WEB_MAX_REQUEST_BYTES", 12 * 1024 * 1024
        ),
        rate_limit_requests=_positive_environment_integer("TRITON_WEB_RATE_LIMIT_REQUESTS", 120),
        rate_limit_window_seconds=_positive_environment_integer(
            "TRITON_WEB_RATE_LIMIT_WINDOW_SECONDS", 60
        ),
    )


@dataclass
class SlidingWindowRateLimiter:
    config: WebRuntimeConfig
    _requests: dict[str, deque[float]] = field(default_factory=dict)
    _lock: Lock = field(default_factory=Lock)

    def retry_after_seconds(self, key: str, now: float | None = None) -> int:
        current_time = monotonic() if now is None else now
        with self._lock:
            requests = self._requests.setdefault(key, deque())
            cutoff = current_time - self.config.rate_limit_window_seconds
            while requests and requests[0] <= cutoff:
                requests.popleft()
            if len(requests) >= self.config.rate_limit_requests:
                retry_after = requests[0] + self.config.rate_limit_window_seconds - current_time
                return max(1, int(retry_after))
            requests.append(current_time)
            return 0
