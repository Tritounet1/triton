import json
import threading
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

import mcp_client
import subagents
from api import ChatResult, call_chat, get_model
from logs import LOGS_FILE, log_event
from main import (
    MAX_ITERATIONS,
    build_system_message,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
)
from projects import Project, create_project, delete_project, get_project, load_projects
from sessions import (
    SESSIONS_DIR,
    allow_always,
    clear_session_project,
    delete_session,
    load_always_allowed,
    load_session,
    load_session_project,
    load_title,
    new_session_path,
    save_session,
    save_session_project,
    save_title,
)
from settings import save_model
from tools import TOOLS, TOOLS_REGISTRY, is_skipped


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    mcp_client.manager.connect_all_enabled()
    yield
    mcp_client.manager.disconnect_all()


app = FastAPI(title="Triton API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    project_id: str | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: str
    approved: bool
    remember: bool = False


class CancelRequest(BaseModel):
    session_id: str


class RenameRequest(BaseModel):
    title: str


class MCPServerCreate(BaseModel):
    name: str
    command: str
    args: list[str] = []
    env: dict[str, str] = {}
    enabled: bool = True


class MCPServerToggle(BaseModel):
    enabled: bool


class ProjectCreate(BaseModel):
    name: str
    folder_path: str


@dataclass
class PendingConfirmation:
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False
    remember: bool = False


PENDING_CONFIRMATIONS: dict[str, PendingConfirmation] = {}

# session ids for which the client asked to stop the agentic loop; checked
# between iterations in run_chat_stream (see chat/cancel below)
CANCELLED_SESSIONS: set[str] = set()


def resolve_session(
    session_id: str | None,
    project_id: str | None = None,
) -> tuple[Path, list[ChatCompletionMessageParam], bool]:
    """Loads the requested session if it exists, otherwise creates a new
    one. Unlike the CLI, the API never silently resumes "the last session":
    it's up to the client to remember its session_id. The boolean indicates
    whether the session was just created (useful to know whether a title
    needs generating). `project_id`, when given, only applies to a newly
    created session: it binds the conversation to that project's folder."""
    if session_id:
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            return path, load_session(path), False

    path = new_session_path()
    project = get_project(project_id) if project_id else None
    if project is not None:
        save_session_project(path.stem, project.id)
    return path, [build_system_message(project)], True


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


MAX_TITLE_CHARS = 60


def generate_conversation_title(first_message: str) -> str:
    """Very short title generated from a conversation's very first message,
    for client-side display only (never sent back to the model afterwards).

    The message is presented as a quote to summarize, not sent as-is in a
    "user" turn: otherwise the model tends to answer it directly (e.g. a
    question like "explain X to me" gets treated as an actual question)
    instead of producing a title."""
    request: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "you summarize messages into a very short title (4 words maximum), in "
            "english, no quotes, no trailing period, no emoji. you never answer the question "
            "asked in the message, you only give a title that summarizes it.",
        },
        {
            "role": "user",
            "content": f"give a very short title for the conversation that starts with this "
            f'message:\n\n"{first_message}"',
        },
    ]
    result = call_chat(request)
    title = (result.content or "new conversation").strip().strip('"')
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def run_chat_stream(
    session_path: Path,
    messages: list[ChatCompletionMessageParam],
    first_message: str | None = None,
) -> Iterator[str]:
    session_id = session_path.stem
    yield sse("session", {"session_id": session_id})

    if first_message is not None:
        title = generate_conversation_title(first_message)
        save_title(session_path.stem, title)
        yield sse("title", {"title": title})

    compressed, compress_message = compress_history_if_needed(messages)
    messages[:] = compressed
    if compress_message:
        yield sse("info", {"message": compress_message})

    iteration = 0
    done = False
    cancelled = False

    while iteration < MAX_ITERATIONS and not done:
        if session_id in CANCELLED_SESSIONS:
            cancelled = True
            break
        iteration += 1
        content_parts: list[str] = []
        reply: ChatResult | None = None

        for event in timed_stream_chat(messages, tools=TOOLS):
            if isinstance(event, str):
                content_parts.append(event)
                yield sse("token", {"text": event})
            else:
                reply = event

        assert reply is not None

        if reply.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": to_tool_call_params(reply.tool_calls),
                }
            )

            for tool_call in reply.tool_calls:
                if tool_call.type != "function":
                    continue

                name = tool_call.function.name
                duration = 0.0

                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = f"error: invalid arguments ({tool_call.function.arguments})"
                    args = {}
                else:
                    tool = TOOLS_REGISTRY.get(name)

                    if tool is None:
                        result = f"unknown tool: {name}"
                    elif tool.read_only or name in load_always_allowed(session_id):
                        result = tool.fn(**args)
                    else:
                        confirmation_id = str(uuid.uuid4())
                        pending = PendingConfirmation()
                        PENDING_CONFIRMATIONS[confirmation_id] = pending

                        yield sse(
                            "confirmation_required",
                            {"confirmation_id": confirmation_id, "tool": name, "args": args},
                        )

                        got_response = pending.event.wait(timeout=300)
                        PENDING_CONFIRMATIONS.pop(confirmation_id, None)

                        if got_response and pending.approved:
                            if pending.remember:
                                allow_always(session_id, name)
                            result = tool.fn(**args)
                        else:
                            result = "action denied by the user"

                yield sse("tool_call", {"tool": name, "args": args, "result": result})

                log_event(
                    type="tool_call",
                    tool=name,
                    args=args,
                    result_preview=result[:300],
                    result_chars=len(result),
                    duration_seconds=round(duration, 3),
                )

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

            continue

        if reply.content is None:
            yield sse("error", {"message": "the model returned neither text nor a tool call."})
            done = True
            continue

        messages.append({"role": "assistant", "content": reply.content})
        yield sse(
            "done",
            {
                "content": reply.content,
                "model": reply.model,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "total_tokens": reply.total_tokens,
            },
        )
        done = True

    CANCELLED_SESSIONS.discard(session_id)

    if not done and not cancelled:
        yield sse("error", {"message": f"limit of {MAX_ITERATIONS} iterations reached."})

    save_session(session_path, messages)


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "model": get_model()}


class ModelUpdate(BaseModel):
    model: str


class ModelInfo(TypedDict):
    id: str
    name: str
    context_length: int
    prompt_price: float
    completion_price: float
    supports_tools: bool


@app.get("/settings/model")
def get_current_model() -> dict[str, str]:
    return {"model": get_model()}


@app.put("/settings/model")
def set_current_model(body: ModelUpdate) -> dict[str, str]:
    save_model(body.model)
    return {"model": body.model}


@app.get("/openrouter/models")
def list_openrouter_models() -> list[ModelInfo]:
    """Proxies OpenRouter's public model catalog (no API key required),
    trimmed to what the desktop app's model picker needs: id/name, context
    size, price per million tokens (OpenRouter reports per-token), and
    whether the model supports function calling at all (this harness is
    unusable with the tool-calling loop otherwise)."""
    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise HTTPException(502, f"could not reach OpenRouter ({e})") from e

    models: list[ModelInfo] = []
    for m in resp.json().get("data", []):
        pricing = m.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt", 0)) * 1_000_000
            completion_price = float(pricing.get("completion", 0)) * 1_000_000
        except (TypeError, ValueError):
            continue
        models.append(
            {
                "id": m["id"],
                "name": m.get("name") or m["id"],
                "context_length": m.get("context_length") or 0,
                "prompt_price": round(prompt_price, 4),
                "completion_price": round(completion_price, 4),
                "supports_tools": "tools" in (m.get("supported_parameters") or []),
            }
        )
    return models


@app.post("/chat")
def chat(body: ChatRequest) -> StreamingResponse:
    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    messages.append({"role": "user", "content": body.message})

    return StreamingResponse(
        run_chat_stream(session_path, messages, first_message=body.message if is_new else None),
        media_type="text/event-stream",
    )


@app.post("/chat/confirm")
def confirm(body: ConfirmRequest) -> dict[str, bool]:
    pending = PENDING_CONFIRMATIONS.get(body.confirmation_id)
    if pending is None:
        raise HTTPException(404, "unknown or already-processed confirmation")

    pending.approved = body.approved
    pending.remember = body.remember
    pending.event.set()
    return {"ok": True}


@app.post("/chat/cancel")
def cancel_chat(body: CancelRequest) -> dict[str, bool]:
    """Marks a session as cancelled: run_chat_stream checks this between
    agentic-loop iterations and stops before starting another one. Doesn't
    interrupt a model call already in flight (see the client-side abort,
    which closes the connection those tokens are streamed to)."""
    CANCELLED_SESSIONS.add(body.session_id)
    return {"ok": True}


@app.get("/sessions")
def list_sessions() -> list[dict[str, str | None]]:
    if not SESSIONS_DIR.exists():
        return []
    ids = sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))
    return [
        {
            "id": session_id,
            "title": load_title(session_id),
            "project_id": load_session_project(session_id),
        }
        for session_id in ids
    ]


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> list[ChatCompletionMessageParam]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    return load_session(path)


@app.put("/sessions/{session_id}/title")
def rename_session(session_id: str, body: RenameRequest) -> dict[str, bool]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    save_title(session_id, body.title)
    return {"ok": True}


@app.delete("/sessions/{session_id}")
def remove_session(session_id: str) -> dict[str, bool]:
    if not delete_session(session_id):
        raise HTTPException(404, "session not found")
    return {"ok": True}


@app.get("/mcp/servers")
def list_mcp_servers() -> list[mcp_client.ServerStatus]:
    return mcp_client.manager.status()


@app.post("/mcp/servers")
def add_mcp_server(body: MCPServerCreate) -> list[mcp_client.ServerStatus]:
    config = mcp_client.MCPServerConfig(
        name=body.name, command=body.command, args=body.args, env=body.env, enabled=body.enabled
    )
    try:
        mcp_client.manager.add_server(config)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return mcp_client.manager.status()


@app.put("/mcp/servers/{name}")
def toggle_mcp_server(name: str, body: MCPServerToggle) -> list[mcp_client.ServerStatus]:
    try:
        mcp_client.manager.set_enabled(name, body.enabled)
    except KeyError as e:
        raise HTTPException(404, "MCP server not found") from e
    return mcp_client.manager.status()


@app.delete("/mcp/servers/{name}")
def remove_mcp_server(name: str) -> list[mcp_client.ServerStatus]:
    mcp_client.manager.remove_server(name)
    return mcp_client.manager.status()


@app.get("/projects")
def list_projects() -> list[Project]:
    return load_projects()


@app.post("/projects")
def add_project(body: ProjectCreate) -> list[Project]:
    folder = Path(body.folder_path)
    if not folder.is_dir():
        raise HTTPException(400, "folder not found")
    create_project(body.name, str(folder))
    return load_projects()


@app.delete("/projects/{project_id}")
def remove_project(project_id: str) -> list[Project]:
    if not delete_project(project_id):
        raise HTTPException(404, "project not found")
    for session_id in (p.stem for p in SESSIONS_DIR.glob("*.json")):
        if load_session_project(session_id) == project_id:
            clear_session_project(session_id)
    return load_projects()


MAX_TREE_ENTRIES = 2000


def _build_tree(directory: Path, budget: list[int]) -> list[dict[str, object]]:
    """Recursively lists a directory's contents (skipping noisy directories
    like .git/node_modules/.venv, see tools.is_skipped), decrementing the
    shared `budget` counter so the whole walk stops once MAX_TREE_ENTRIES is
    reached rather than per-directory."""
    entries: list[dict[str, object]] = []
    try:
        children = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    except OSError:
        return entries

    for child in children:
        if budget[0] <= 0:
            break
        if is_skipped(child):
            continue
        budget[0] -= 1
        if child.is_dir():
            entries.append(
                {
                    "name": child.name,
                    "path": str(child),
                    "is_dir": True,
                    "children": _build_tree(child, budget),
                }
            )
        else:
            entries.append({"name": child.name, "path": str(child), "is_dir": False})

    return entries


@app.get("/projects/{project_id}/tree")
def get_project_tree(project_id: str) -> dict[str, object]:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(404, "project not found")

    root = Path(project.folder_path)
    if not root.is_dir():
        raise HTTPException(404, "project folder no longer exists")

    budget = [MAX_TREE_ENTRIES]
    tree = _build_tree(root, budget)
    return {"tree": tree, "truncated": budget[0] <= 0}


@app.get("/subagents")
def list_subagents() -> list[subagents.SubagentTask]:
    return subagents.list_tasks()


@app.get("/logs")
def get_logs(limit: int = 500) -> list[dict[str, object]]:
    """Raw events from logs/events.jsonl (model_call / tool_call), most
    recent first. `limit` bounds the response so a file that grew huge is
    never returned all at once."""
    if not LOGS_FILE.exists():
        return []
    lines = [line for line in LOGS_FILE.read_text().splitlines() if line.strip()]
    events = [json.loads(line) for line in lines[-limit:]]
    events.reverse()
    return events


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
