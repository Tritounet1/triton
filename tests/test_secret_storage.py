"""Credentials migrate to the Keychain and never remain in JSON configs."""

import json

from triton import mcp_client
from triton.storage import settings


def test_legacy_settings_key_migrates_and_is_removed(tmp_path, monkeypatch):
    settings_file = tmp_path / "settings.json"
    settings_file.write_text('{"openrouter_api_key": "legacy-secret", "model": "x"}')
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)
    stored: dict[str, str] = {}
    monkeypatch.setattr(settings, "get_secret", stored.get)
    monkeypatch.setattr(settings, "set_secret", lambda key, value: stored.__setitem__(key, value))

    assert settings.load_openrouter_api_key() == "legacy-secret"
    assert stored["openrouter_api_key"] == "legacy-secret"
    assert json.loads(settings_file.read_text()) == {"model": "x"}


def test_mcp_config_persists_env_names_but_not_values(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp_servers.json"
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", config_path)
    stored: dict[str, str] = {}
    monkeypatch.setattr(mcp_client, "set_secret", lambda key, value: stored.__setitem__(key, value))
    monkeypatch.setattr(mcp_client, "get_secret", stored.get)
    config = mcp_client.MCPServerConfig(
        name="notes", command="npx", args=["notes"], env={"TOKEN": "super-secret"}
    )

    mcp_client.save_configs([config])

    persisted = json.loads(config_path.read_text())
    assert "super-secret" not in config_path.read_text()
    assert persisted[0]["env"] == {}
    assert persisted[0]["env_keys"] == ["TOKEN"]
    assert stored["mcp:notes:TOKEN"] == "super-secret"
    assert mcp_client.load_configs()[0].env == {"TOKEN": "super-secret"}


def test_mcp_config_migrates_angle_bracketed_http_arguments(tmp_path, monkeypatch):
    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            [
                {
                    "name": "notes",
                    "command": "npx",
                    "args": ["-y", "mcp-remote", "<https://example.com/mcp>"],
                    "env": {},
                    "env_keys": [],
                    "enabled": True,
                }
            ]
        )
    )
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", config_path)
    monkeypatch.setattr(mcp_client, "get_secret", lambda _: None)
    monkeypatch.setattr(mcp_client, "set_secret", lambda *_: None)

    configs = mcp_client.load_configs()

    assert configs[0].args[-1] == "https://example.com/mcp"
    assert json.loads(config_path.read_text())[0]["args"][-1] == "https://example.com/mcp"
