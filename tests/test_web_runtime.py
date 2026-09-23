import pytest

from triton.web_runtime import load_web_runtime_config


def test_runtime_configuration_defaults_max_request_bytes(monkeypatch):
    monkeypatch.delenv("TRITON_WEB_MAX_REQUEST_BYTES", raising=False)

    config = load_web_runtime_config()

    assert config.max_request_bytes == 12 * 1024 * 1024


def test_runtime_configuration_rejects_invalid_values(monkeypatch):
    monkeypatch.setenv("TRITON_WEB_MAX_REQUEST_BYTES", "zero")

    with pytest.raises(ValueError, match="TRITON_WEB_MAX_REQUEST_BYTES"):
        load_web_runtime_config()
