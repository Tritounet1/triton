"""MCP (Model Context Protocol) integration: connects the harness to
external tool servers instead of hand-coding each tool as in tools.py. A
configured MCP server (same format as Claude Desktop: command/args/env)
shows up as extra tools in tools.TOOLS_REGISTRY, available to the agentic
loop in main.py and server.py without any change on their side.

The MCP SDK is async; the rest of the harness (Tool.fn) is synchronous.
Rather than rewriting the whole agentic loop as async, a dedicated asyncio
loop runs in a background thread and hosts all open MCP sessions; each
synchronous Tool.fn submits its coroutine to that loop via
asyncio.run_coroutine_threadsafe() and waits for the result.
"""

import asyncio
import json
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TypedDict

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import TextContent
from mcp.types import Tool as MCPTool

from tools import TOOLS_REGISTRY, Tool, rebuild_tools_list

CONFIG_PATH = Path(__file__).parent / "mcp_servers.json"
MCP_PREFIX = "mcp__"
CALL_TIMEOUT = 60


class ServerStatus(TypedDict):
    name: str
    command: str
    args: list[str]
    enabled: bool
    connected: bool
    error: str | None
    tools: list[str]


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def load_configs() -> list[MCPServerConfig]:
    if not CONFIG_PATH.exists():
        return []
    raw = json.loads(CONFIG_PATH.read_text())
    return [MCPServerConfig(**c) for c in raw]


def save_configs(configs: list[MCPServerConfig]) -> None:
    CONFIG_PATH.write_text(json.dumps([asdict(c) for c in configs], ensure_ascii=False, indent=2))


@dataclass
class ServerConnection:
    config: MCPServerConfig
    connected: bool = False
    error: str | None = None
    tool_names: list[str] = field(default_factory=list)
    # the asyncio task keeping stdio_client()/ClientSession() open, and the
    # event that signals it to close them. anyio (used internally by
    # stdio_client) attaches its task groups to the task that opened them:
    # opening and closing must happen in the SAME task, hence using a
    # long-running task instead of two separate connect/disconnect
    # coroutines submitted independently to the loop.
    task: "asyncio.Task[None] | None" = field(default=None, repr=False)
    stop_event: asyncio.Event | None = field(default=None, repr=False)


def tool_key(server_name: str, tool_name: str) -> str:
    return f"{MCP_PREFIX}{server_name}__{tool_name}"


class MCPManager:
    """Background asyncio loop hosting all connected MCP sessions, with a
    fully synchronous API for the rest of the harness."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self.connections: dict[str, ServerConnection] = {}

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run_coro(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=CALL_TIMEOUT)

    def _make_tool_fn(
        self, server_name: str, session: ClientSession, mcp_tool_name: str
    ) -> Callable[..., str]:
        def fn(**kwargs: object) -> str:
            async def call() -> str:
                result = await session.call_tool(mcp_tool_name, kwargs)
                texts = [b.text for b in result.content if isinstance(b, TextContent)]
                text = "\n".join(texts) if texts else "(no text content returned)"
                if result.is_error:
                    return f"error (MCP server '{server_name}', tool {mcp_tool_name}): {text}"
                return text

            return self._run_coro(call())

        return fn

    def _register_tools(
        self, server_name: str, session: ClientSession, mcp_tools: list[MCPTool]
    ) -> None:
        for key in [k for k in TOOLS_REGISTRY if k.startswith(f"{MCP_PREFIX}{server_name}__")]:
            del TOOLS_REGISTRY[key]

        for t in mcp_tools:
            key = tool_key(server_name, t.name)
            description = t.description or t.name
            read_only = bool(t.annotations and t.annotations.read_only_hint)
            TOOLS_REGISTRY[key] = Tool(
                schema={
                    "type": "function",
                    "function": {
                        "name": key,
                        "description": f"{description} (via MCP server '{server_name}')",
                        "parameters": t.input_schema or {"type": "object", "properties": {}},
                    },
                },
                fn=self._make_tool_fn(server_name, session, t.name),
                read_only=read_only,
            )

        rebuild_tools_list()

    async def _server_task(
        self,
        config: MCPServerConfig,
        ready: "asyncio.Future[ServerConnection]",
        stop: asyncio.Event,
    ) -> None:
        """Long-running background task: opens the connection, keeps it open
        until the stop signal, then closes it, all within the same task
        (anyio constraint, see ServerConnection.task)."""
        try:
            params = StdioServerParameters(
                command=config.command, args=config.args, env=config.env or None
            )
            async with (
                stdio_client(params) as (read, write),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.list_tools()
                self._register_tools(config.name, session, result.tools)
                if not ready.done():
                    ready.set_result(
                        ServerConnection(
                            config=config,
                            connected=True,
                            tool_names=[t.name for t in result.tools],
                        )
                    )
                await stop.wait()
        except Exception as e:
            if not ready.done():
                ready.set_result(ServerConnection(config=config, error=f"{type(e).__name__}: {e}"))

    async def _start(self, config: MCPServerConfig) -> ServerConnection:
        ready: asyncio.Future[ServerConnection] = self._loop.create_future()
        stop = asyncio.Event()
        task = asyncio.create_task(self._server_task(config, ready, stop))
        conn = await ready
        conn.task = task
        conn.stop_event = stop
        return conn

    async def _stop(self, conn: ServerConnection) -> None:
        if conn.stop_event is not None:
            conn.stop_event.set()
        if conn.task is not None:
            await conn.task

    def _clear_tools(self, server_name: str) -> None:
        for key in [k for k in TOOLS_REGISTRY if k.startswith(f"{MCP_PREFIX}{server_name}__")]:
            del TOOLS_REGISTRY[key]
        rebuild_tools_list()

    # ---- Synchronous API called by server.py / main.py --------------------

    def connect(self, name: str) -> ServerConnection:
        configs = {c.name: c for c in load_configs()}
        config = configs.get(name)
        if config is None:
            raise KeyError(name)

        existing = self.connections.get(name)
        if existing and existing.connected:
            self._run_coro(self._stop(existing))

        conn = self._run_coro(self._start(config))
        self.connections[name] = conn
        return conn

    def disconnect(self, name: str) -> None:
        conn = self.connections.get(name)
        if conn and conn.connected:
            self._run_coro(self._stop(conn))
        self._clear_tools(name)
        self.connections.pop(name, None)

    def connect_all_enabled(self) -> None:
        for config in load_configs():
            if config.enabled:
                try:
                    self.connect(config.name)
                except Exception as e:
                    self.connections[config.name] = ServerConnection(
                        config=config, error=f"{type(e).__name__}: {e}"
                    )

    def disconnect_all(self) -> None:
        for name in list(self.connections):
            self.disconnect(name)

    def status(self) -> list[ServerStatus]:
        configs = load_configs()
        out: list[ServerStatus] = []
        for config in configs:
            conn = self.connections.get(config.name)
            out.append(
                {
                    "name": config.name,
                    "command": config.command,
                    "args": config.args,
                    "enabled": config.enabled,
                    "connected": bool(conn and conn.connected),
                    "error": conn.error if conn else None,
                    "tools": conn.tool_names if conn else [],
                }
            )
        return out

    def add_server(self, config: MCPServerConfig) -> ServerConnection | None:
        configs = load_configs()
        if any(c.name == config.name for c in configs):
            raise ValueError(f"a server named '{config.name}' already exists")
        configs.append(config)
        save_configs(configs)
        return self.connect(config.name) if config.enabled else None

    def remove_server(self, name: str) -> None:
        self.disconnect(name)
        save_configs([c for c in load_configs() if c.name != name])

    def set_enabled(self, name: str, enabled: bool) -> ServerConnection | None:
        configs = load_configs()
        found = False
        for c in configs:
            if c.name == name:
                c.enabled = enabled
                found = True
        if not found:
            raise KeyError(name)
        save_configs(configs)
        if enabled:
            return self.connect(name)
        self.disconnect(name)
        return None


manager = MCPManager()
