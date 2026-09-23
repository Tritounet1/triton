"""MCPManager.update_server: edits an existing MCP server's config in
place (rename included) instead of the model/UI having to delete and
re-add it. Every config here stays enabled=False so update_server's
internal connect()/disconnect() calls never try to actually spawn or
tear down a real subprocess."""

import pytest

from triton import mcp_client


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mcp_client, "CONFIG_PATH", tmp_path / "mcp_servers.json")
    stored: dict[str, str] = {}
    monkeypatch.setattr(mcp_client, "set_secret", lambda key, value: stored.__setitem__(key, value))
    monkeypatch.setattr(mcp_client, "get_secret", stored.get)


def test_update_server_replaces_command_and_args():
    mcp_client.manager.add_server(
        mcp_client.MCPServerConfig(
            name="notes", command="npx", args=["-y", "notes-mcp"], enabled=False
        )
    )

    mcp_client.manager.update_server(
        "notes",
        mcp_client.MCPServerConfig(
            name="notes", command="uvx", args=["notes-mcp-v2"], enabled=False
        ),
    )

    [config] = mcp_client.load_configs()
    assert config.command == "uvx"
    assert config.args == ["notes-mcp-v2"]


def test_update_server_can_rename():
    mcp_client.manager.add_server(
        mcp_client.MCPServerConfig(name="notes", command="npx", enabled=False)
    )

    mcp_client.manager.update_server(
        "notes", mcp_client.MCPServerConfig(name="notes-v2", command="npx", enabled=False)
    )

    names = [c.name for c in mcp_client.load_configs()]
    assert names == ["notes-v2"]


def test_update_server_rejects_a_rename_that_collides():
    mcp_client.manager.add_server(
        mcp_client.MCPServerConfig(name="a", command="npx", enabled=False)
    )
    mcp_client.manager.add_server(
        mcp_client.MCPServerConfig(name="b", command="npx", enabled=False)
    )

    with pytest.raises(ValueError, match="already exists"):
        mcp_client.manager.update_server(
            "a", mcp_client.MCPServerConfig(name="b", command="npx", enabled=False)
        )


def test_update_server_404s_for_an_unknown_name():
    with pytest.raises(KeyError):
        mcp_client.manager.update_server(
            "ghost", mcp_client.MCPServerConfig(name="ghost", command="npx", enabled=False)
        )


def test_update_server_merges_env_instead_of_replacing_it():
    mcp_client.manager.add_server(
        mcp_client.MCPServerConfig(
            name="notes",
            command="npx",
            env={"API_KEY": "secret-1", "REGION": "eu"},
            enabled=False,
        )
    )

    mcp_client.manager.update_server(
        "notes",
        mcp_client.MCPServerConfig(
            name="notes", command="npx", env={"API_KEY": "secret-2"}, enabled=False
        ),
    )

    [config] = mcp_client.load_configs()
    assert config.env == {"API_KEY": "secret-2", "REGION": "eu"}
