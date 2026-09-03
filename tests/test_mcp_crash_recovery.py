"""MCPManager._server_task: a server that fails during its initial
handshake was already handled (connect()/_start() surfaces the error, no
crash). A server that connects fine and then dies mid-session (its
subprocess crashing, not a failed handshake) was not: the exception still
landed in _server_task's except clause, but since `ready` was already
resolved by then, nothing updated the live entry in self.connections -
it kept claiming connected=True with a now-dead tool list, so a call
against one of its tools would just hang until CALL_TIMEOUT instead of
failing immediately with a clear reason. No real subprocess: stdio_client/
ClientSession are monkeypatched to fakes."""

import asyncio
from types import SimpleNamespace

import pytest

from triton import mcp_client
from triton.mcp_client import MCPManager, MCPServerConfig
from triton.tools import TOOLS_REGISTRY


class _FakeReadWriteCM:
    async def __aenter__(self):
        return (object(), object())

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeSession:
    def __init__(self, tools):
        self._tools = tools

    async def initialize(self):
        return None

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)


class _FakeClientSessionCM:
    """Enters fine (hands back the fake session) but raises on exit - the
    server process having died mid-session is exactly the kind of thing
    that makes tearing the connection down blow up."""

    def __init__(self, session, exit_error):
        self._session = session
        self._exit_error = exit_error

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if self._exit_error is not None:
            raise self._exit_error
        return False


@pytest.fixture
def manager():
    m = MCPManager()
    yield m
    for key in [k for k in TOOLS_REGISTRY if k.startswith(f"{mcp_client.MCP_PREFIX}test-mcp__")]:
        del TOOLS_REGISTRY[key]


def _fake_tool(name="do_a_thing"):
    return SimpleNamespace(
        name=name, description="does a thing", annotations=None, input_schema=None
    )


def test_a_crash_during_the_initial_handshake_resolves_ready_with_an_error(manager, monkeypatch):
    monkeypatch.setattr(mcp_client, "stdio_client", lambda params: _FakeReadWriteCM())

    def fake_client_session(read, write):
        class _RaisesOnEnter:
            async def __aenter__(self):
                raise ConnectionRefusedError("could not start the server")

            async def __aexit__(self, *exc):
                return False

        return _RaisesOnEnter()

    monkeypatch.setattr(mcp_client, "ClientSession", fake_client_session)

    config = MCPServerConfig(name="test-mcp", command="does-not-matter")

    async def _run():
        ready: asyncio.Future = manager._loop.create_future()
        stop = asyncio.Event()
        stop.set()
        await manager._server_task(config, ready, stop)
        return ready.result()

    result = manager._run_coro(_run())

    assert result.connected is False
    assert "ConnectionRefusedError" in (result.error or "")
    assert "test-mcp" not in manager.connections


def test_a_crash_after_connecting_updates_the_live_connection(manager, monkeypatch):
    monkeypatch.setattr(mcp_client, "stdio_client", lambda params: _FakeReadWriteCM())

    fake_session = _FakeSession(tools=[_fake_tool()])
    monkeypatch.setattr(
        mcp_client,
        "ClientSession",
        lambda read, write: _FakeClientSessionCM(
            fake_session, exit_error=ConnectionResetError("server process died")
        ),
    )

    config = MCPServerConfig(name="test-mcp", command="does-not-matter")
    # simulates connect() having already stored the successful result -
    # the exact state right before the mid-session crash this test drives
    manager.connections["test-mcp"] = mcp_client.ServerConnection(
        config=config, connected=True, tool_names=["do_a_thing"]
    )

    async def _run():
        ready: asyncio.Future = manager._loop.create_future()
        stop = asyncio.Event()
        stop.set()
        await manager._server_task(config, ready, stop)

    manager._run_coro(_run())

    conn = manager.connections["test-mcp"]
    assert conn.connected is False
    assert "ConnectionResetError" in (conn.error or "")
    assert f"{mcp_client.MCP_PREFIX}test-mcp__do_a_thing" not in TOOLS_REGISTRY
