from dataclasses import dataclass
from os import getenv


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


def load_web_runtime_config() -> WebRuntimeConfig:
    return WebRuntimeConfig(
        max_request_bytes=_positive_environment_integer(
            "TRITON_WEB_MAX_REQUEST_BYTES", 12 * 1024 * 1024
        ),
    )
