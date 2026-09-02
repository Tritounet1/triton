"""Lets the model configure a new MCP server itself, instead of the user
always having to do it by hand in the Settings UI (POST /mcp/servers in
server.py does the exact same thing, for that UI). triton.mcp_client is
imported lazily inside the function body, not at module level: it does
`from triton.tools import TOOLS_REGISTRY, ...` itself (see its own
docstring), so importing it here at module level would be circular -
triton.tools/__init__.py assembles this module into TOOLS_REGISTRY before
triton.mcp_client could ever finish importing it back. subagents.py hits
the exact same shape and resolves it the same way (see its own
TOOLS_REGISTRY import inside dispatch())."""

from triton.tools._shared import Tool


def add_mcp_server(
    name: str,
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    enabled: bool = True,
) -> str:
    from triton import mcp_client

    config = mcp_client.MCPServerConfig(
        name=name, command=command, args=args or [], env=env or {}, enabled=enabled
    )
    try:
        mcp_client.manager.add_server(config)
    except ValueError as e:
        # a server with this name already exists - mcp_client.manager
        # itself raises this, the same case POST /mcp/servers turns into
        # an HTTP 409
        return f"error: {e}"

    entry = next((s for s in mcp_client.manager.status() if s["name"] == name), None)
    if entry is None:
        return f"error: server '{name}' was not found right after being added"
    if not enabled:
        return f"MCP server '{name}' added, disabled (as requested)."
    if entry["connected"]:
        tool_names = ", ".join(entry["tools"]) if entry["tools"] else "(no tools exposed)"
        return f"MCP server '{name}' added and connected. Tools now available: {tool_names}"
    return f"MCP server '{name}' added but failed to connect: {entry['error']}"


REGISTRY: dict[str, Tool] = {
    "add_mcp_server": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "add_mcp_server",
                "description": "Configures and connects a new MCP (Model Context Protocol) "
                "server, exposing its tools to this conversation immediately (no restart "
                "needed) - the same thing the user can do by hand in Settings. This "
                "launches `command` as a real subprocess with the given args/env, outside "
                "the project sandbox entirely: only use this for a legitimate MCP server "
                "the user explicitly asked to connect (e.g. a package they named, or a "
                "command they gave you directly) - never invent one or run something just "
                "because it seems useful. Not scoped to a project: works the same "
                "regardless of which one (if any) this conversation has selected.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Unique name for this server - fails if one "
                            "with this name already exists.",
                        },
                        "command": {
                            "type": "string",
                            "description": "Executable to launch the server with (e.g. "
                            "'npx', 'uvx', 'python3').",
                        },
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Command-line arguments (e.g. the package name "
                            "for npx/uvx). Default: none.",
                        },
                        "env": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "description": "Environment variables the server process needs "
                            "(e.g. an API key it reads itself). Default: none.",
                        },
                        "enabled": {
                            "type": "boolean",
                            "description": "Whether to connect immediately. Default: true.",
                        },
                    },
                    "required": ["name", "command"],
                },
            },
        },
        fn=add_mcp_server,
        read_only=False,
    ),
}
