"""add_mcp_server (tools/mcp.py): lets the model configure a new MCP
server itself instead of the user always doing it by hand in Settings -
POST /mcp/servers in server.py does the exact same thing, for that UI.
mcp_client.manager is faked out entirely here: actually connecting a real
MCP server spawns a real subprocess over stdio, nothing this test needs
to exercise - only that add_mcp_server builds the right config, surfaces
mcp_client.manager.add_server's ValueError (duplicate name) as a plain
error string instead of raising, and reports connected/failed/disabled
correctly from manager.status()."""

from dataclasses import dataclass, field

import pytest

from triton import mcp_client
from triton.tools.mcp import add_mcp_server


@dataclass
class _FakeManager:
    added: list[mcp_client.MCPServerConfig] = field(default_factory=list)
    connect_error: str | None = None

    def add_server(self, config: mcp_client.MCPServerConfig) -> None:
        if any(c.name == config.name for c in self.added):
            raise ValueError(f"a server named '{config.name}' already exists")
        self.added.append(config)

    def status(self) -> list[dict]:
        connected = self.connect_error is None
        return [
            {
                "name": c.name,
                "command": c.command,
                "args": c.args,
                "enabled": c.enabled,
                "connected": c.enabled and connected,
                "error": self.connect_error if c.enabled else None,
                "tools": ["do_a_thing"] if c.enabled and connected else [],
            }
            for c in self.added
        ]


@pytest.fixture
def fake_manager(monkeypatch):
    fake = _FakeManager()
    monkeypatch.setattr(mcp_client, "manager", fake)
    return fake


def test_adds_and_connects_a_new_server(fake_manager):
    result = add_mcp_server("weather", "npx", args=["-y", "weather-mcp"])

    assert "added and connected" in result
    assert "do_a_thing" in result
    assert fake_manager.added[0].name == "weather"
    assert fake_manager.added[0].args == ["-y", "weather-mcp"]


def test_rejects_a_duplicate_name(fake_manager):
    add_mcp_server("weather", "npx", args=["-y", "weather-mcp"])

    result = add_mcp_server("weather", "npx", args=["-y", "weather-mcp"])

    assert result.startswith("error:")
    assert "already exists" in result
    assert len(fake_manager.added) == 1


def test_disabled_server_is_added_without_connecting(fake_manager):
    result = add_mcp_server("weather", "npx", enabled=False)

    assert "added, disabled" in result
    assert fake_manager.added[0].enabled is False


def test_reports_a_connection_failure(fake_manager):
    fake_manager.connect_error = "ENOENT: command not found"

    result = add_mcp_server("weather", "does-not-exist")

    assert "failed to connect" in result
    assert "ENOENT" in result


def test_env_and_args_default_to_empty(fake_manager):
    add_mcp_server("weather", "npx")

    config = fake_manager.added[0]
    assert config.args == []
    assert config.env == {}
