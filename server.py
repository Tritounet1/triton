import json
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict, cast

import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from triton import background_tasks, mcp_client
from triton.agents import orchestrator, subagents
from triton.llm.api import ChatResult, call_chat, get_model, is_api_key_configured
from triton.llm.chat_loop import (
    MAX_ITERATIONS,
    build_system_message,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
)
from triton.llm.model_roles import ROLE_MODELS
from triton.storage.logs import LOGS_FILE, log_event
from triton.storage.projects import (
    Project,
    create_project,
    delete_project,
    get_project,
    load_projects,
    rename_project,
)
from triton.storage.sessions import (
    SESSIONS_DIR,
    allow_always,
    clear_session_project,
    delete_session,
    is_pinned,
    load_always_allowed,
    load_session,
    load_session_model,
    load_session_project,
    load_title,
    new_session_path,
    save_session,
    save_session_model,
    save_session_project,
    save_title,
    set_pinned,
)
from triton.storage.settings import (
    load_monthly_budget,
    load_role_model_overrides,
    save_model,
    save_monthly_budget,
    save_openrouter_api_key,
    save_role_model_override,
)
from triton.storage.snapshots import get_snapshot
from triton.tools import (
    TOOLS,
    TOOLS_REGISTRY,
    WRITE_TOOL_NAMES,
    RestoreError,
    discard_snapshot,
    enforce_project_sandbox,
    ensure_snapshot,
    invoke_tool,
    is_skipped,
    restore_snapshot,
)


class _QuietPollingEndpoints(logging.Filter):
    """The desktop app polls a handful of endpoints every 1.5-3s
    (background tasks, subagents, an in-flight multi-agent run) for as
    long as it's open - uvicorn's access log otherwise fills up with
    almost nothing else, drowning out anything worth actually noticing.
    Drops just those access log lines; POSTs, errors, and every other
    route still log normally. Uvicorn's h11 protocol logs each request as
    access_logger.info('%s - "%s %s HTTP/%s" %d', client_addr, method,
    path, http_version, status) - record.args[2] is the path."""

    _quiet_prefixes = ("/background_tasks", "/subagents", "/orchestrator/")

    def filter(self, record: logging.LogRecord) -> bool:
        if not isinstance(record.args, tuple) or len(record.args) < 3:
            return True
        path = record.args[2]
        return not (isinstance(path, str) and path.startswith(self._quiet_prefixes))


logging.getLogger("uvicorn.access").addFilter(_QuietPollingEndpoints())


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


class Attachment(BaseModel):
    name: str = ""
    # a full data URL ("data:image/png;base64,...."), exactly what the
    # OpenAI/OpenRouter image_url.url field accepts - no server-side
    # decoding needed, it's forwarded to the model as-is.
    data_url: str


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    project_id: str | None = None
    attachments: list[Attachment] = []


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


class ProjectRename(BaseModel):
    name: str


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

    if not is_api_key_configured():
        yield sse(
            "error",
            {
                "message": "Aucune clé API OpenRouter configurée. Ouvre les Paramètres "
                "(icône en bas de la barre latérale) pour en ajouter une.",
            },
        )
        return

    project_id = load_session_project(session_id)
    project = get_project(project_id) if project_id else None
    session_model = load_session_model(session_id)

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

        for event in timed_stream_chat(
            messages, tools=TOOLS, model=session_model, session_id=session_id
        ):
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
                    sandbox_error = enforce_project_sandbox(name, args, project)
                    tool = TOOLS_REGISTRY.get(name)

                    if sandbox_error is None and tool is not None and name in WRITE_TOOL_NAMES:
                        # snapshot before the write actually runs, not after
                        # approval below - taking it is harmless even if this
                        # particular call ends up denied, and it guarantees
                        # the safety net is in place before any write from
                        # this session could have landed (see tools/snapshot.py)
                        ensure_snapshot(project, session_id)

                    if sandbox_error is not None:
                        result = sandbox_error
                    elif tool is None:
                        result = f"unknown tool: {name}"
                    elif tool.read_only or name in load_always_allowed(session_id):
                        result = invoke_tool(tool, name, args, session_id)
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
                            result = invoke_tool(tool, name, args, session_id)
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
            if reply.finish_reason == "length":
                # the model hit the output token limit before producing any
                # visible content or tool call at all (common with reasoning
                # models, which can burn the whole budget on hidden
                # reasoning tokens) - recoverable, unlike a genuinely empty
                # response: nudge it and let the loop retry, bounded by the
                # same MAX_ITERATIONS as everything else.
                yield sse(
                    "info",
                    {
                        "message": "the model's response was cut off by the output length "
                        "limit before producing anything usable - asking it to continue.",
                    },
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Your last response was cut off by the output length "
                        "limit before it produced any visible content or tool call. "
                        "Continue, breaking the work into smaller steps if that's what "
                        "caused it (e.g. write large files in smaller edits).",
                    }
                )
                continue
            yield sse("error", {"message": "the model returned neither text nor a tool call."})
            done = True
            continue

        messages.append(
            cast(
                ChatCompletionMessageParam,
                {"role": "assistant", "content": reply.content, "model": reply.model},
            )
        )
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


class BudgetUpdate(BaseModel):
    monthly_budget_usd: float | None = None


class ModelInfo(TypedDict):
    id: str
    name: str
    context_length: int
    prompt_price: float
    completion_price: float
    supports_tools: bool
    supports_images: bool
    supports_files: bool


@app.get("/settings/model")
def get_current_model() -> dict[str, str]:
    return {"model": get_model()}


@app.put("/settings/model")
def set_current_model(body: ModelUpdate) -> dict[str, str]:
    save_model(body.model)
    return {"model": body.model}


@app.get("/settings/budget")
def get_monthly_budget() -> dict[str, float | None]:
    return {"monthly_budget_usd": load_monthly_budget()}


@app.put("/settings/budget")
def set_monthly_budget(body: BudgetUpdate) -> dict[str, float | None]:
    save_monthly_budget(body.monthly_budget_usd)
    return {"monthly_budget_usd": body.monthly_budget_usd}


class ApiKeyUpdate(BaseModel):
    api_key: str


@app.get("/settings/api_key")
def get_api_key_status() -> dict[str, bool]:
    # never echoes the key itself back, only whether one is configured -
    # the Settings UI shows a blank password field either way, never the
    # real value once saved.
    return {"configured": is_api_key_configured()}


@app.put("/settings/api_key")
def set_api_key(body: ApiKeyUpdate) -> dict[str, bool]:
    save_openrouter_api_key(body.api_key.strip() or None)
    return {"configured": is_api_key_configured()}


class RoleModelInfo(TypedDict):
    role: str
    default_model: str
    model: str
    is_override: bool


class RoleModelUpdate(BaseModel):
    role: str
    # None (or omitted) clears the override, falling back to ROLE_MODELS's
    # default for that role again.
    model: str | None = None


def _role_models_status() -> list[RoleModelInfo]:
    overrides = load_role_model_overrides()
    return [
        {
            "role": role,
            "default_model": default,
            "model": overrides.get(role, default),
            "is_override": role in overrides,
        }
        for role, default in ROLE_MODELS.items()
    ]


@app.get("/settings/role_models")
def get_role_models() -> list[RoleModelInfo]:
    return _role_models_status()


@app.put("/settings/role_models")
def set_role_model(body: RoleModelUpdate) -> list[RoleModelInfo]:
    if body.role not in ROLE_MODELS:
        raise HTTPException(404, f"unknown role: {body.role}")
    save_role_model_override(body.role, body.model)
    return _role_models_status()


# short-lived: the catalog itself barely changes minute to minute, but a
# short TTL still means the desktop app's own startup (modelsCatalog in
# App.tsx) and every time Settings > Modele is opened don't each cost a
# fresh round-trip to OpenRouter - see pricing.py's get_price() for the
# same cache-with-TTL shape, kept separate since that one only needs
# prompt/completion price per model, not this endpoint's fuller shape.
_MODELS_CACHE_TTL_SECONDS = 300
_models_cache: list[ModelInfo] | None = None
_models_cache_time = 0.0


@app.get("/openrouter/models")
def list_openrouter_models() -> list[ModelInfo]:
    """Proxies OpenRouter's public model catalog (no API key required),
    trimmed to what the desktop app's model picker needs: id/name, context
    size, price per million tokens (OpenRouter reports per-token), whether
    the model supports function calling at all (this harness is unusable
    with the tool-calling loop otherwise), and whether it accepts image
    and/or PDF input (used to enable/disable the composer's attach
    button)."""
    global _models_cache, _models_cache_time

    cache_age = time.monotonic() - _models_cache_time
    if _models_cache is not None and cache_age < _MODELS_CACHE_TTL_SECONDS:
        return _models_cache

    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        if _models_cache is not None:
            # OpenRouter hiccup: serve the last known catalog rather than
            # break the model picker over a transient network error.
            return _models_cache
        raise HTTPException(502, f"could not reach OpenRouter ({e})") from e

    models: list[ModelInfo] = []
    for m in resp.json().get("data", []):
        pricing = m.get("pricing") or {}
        try:
            prompt_price = float(pricing.get("prompt", 0)) * 1_000_000
            completion_price = float(pricing.get("completion", 0)) * 1_000_000
        except (TypeError, ValueError):
            continue
        architecture = m.get("architecture") or {}
        models.append(
            {
                "id": m["id"],
                "name": m.get("name") or m["id"],
                "context_length": m.get("context_length") or 0,
                "prompt_price": round(prompt_price, 4),
                "completion_price": round(completion_price, 4),
                "supports_tools": "tools" in (m.get("supported_parameters") or []),
                "supports_images": "image" in (architecture.get("input_modalities") or []),
                "supports_files": "file" in (architecture.get("input_modalities") or []),
            }
        )
    _models_cache = models
    _models_cache_time = time.monotonic()
    return models


# images and PDFs only: other file types are handled inconsistently across
# providers (some accept arbitrary documents, most don't), whereas these two
# map to well-defined OpenAI-compatible content parts (image_url and
# OpenRouter's file) that every model advertising the matching input
# modality accepts.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024


def validate_attachments(attachments: list[Attachment]) -> None:
    for a in attachments:
        is_image_or_pdf = a.data_url.startswith(("data:image/", "data:application/pdf"))
        if not is_image_or_pdf:
            raise HTTPException(400, f"attachment {a.name!r} is not a supported image or PDF")
        _, _, b64_payload = a.data_url.partition(",")
        if len(b64_payload) * 3 // 4 > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                400,
                f"attachment {a.name!r} exceeds the "
                f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB limit",
            )


def attachment_content_part(a: Attachment) -> dict[str, object]:
    if a.data_url.startswith("data:image/"):
        return {"type": "image_url", "image_url": {"url": a.data_url}}
    # OpenRouter's own extension to the OpenAI schema for document input,
    # understood natively by every model that lists "file" in
    # architecture.input_modalities (no parsing plugin needed there).
    return {"type": "file", "file": {"filename": a.name or "document.pdf", "file_data": a.data_url}}


def build_user_content(text: str, attachments: list[Attachment]) -> str | list[dict[str, object]]:
    if not attachments:
        return text
    parts: list[dict[str, object]] = []
    if text:
        parts.append({"type": "text", "text": text})
    parts.extend(attachment_content_part(a) for a in attachments)
    return parts


@app.post("/chat")
def chat(body: ChatRequest) -> StreamingResponse:
    validate_attachments(body.attachments)
    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    messages.append(
        cast(
            ChatCompletionMessageParam,
            {"role": "user", "content": build_user_content(body.message, body.attachments)},
        )
    )

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
def list_sessions() -> list[dict[str, str | bool | None]]:
    if not SESSIONS_DIR.exists():
        return []
    ids = sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))
    return [
        {
            "id": session_id,
            "title": load_title(session_id),
            "project_id": load_session_project(session_id),
            "pinned": is_pinned(session_id),
        }
        for session_id in ids
    ]


class PinRequest(BaseModel):
    pinned: bool


@app.put("/sessions/{session_id}/pin")
def pin_session(session_id: str, body: PinRequest) -> dict[str, bool]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    set_pinned(session_id, body.pinned)
    return {"ok": True}


class ModelRequest(BaseModel):
    model: str


@app.get("/sessions/{session_id}/model")
def get_session_model(session_id: str) -> dict[str, str | None]:
    """The /model command's override for this conversation, if any (see
    load_session_model) - None means it's using the global default
    (GET /settings/model), like every conversation before this existed."""
    return {"model": load_session_model(session_id)}


@app.put("/sessions/{session_id}/model")
def set_session_model(session_id: str, body: ModelRequest) -> dict[str, str]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    save_session_model(session_id, body.model)
    return {"model": body.model}


class SessionCost(BaseModel):
    calls: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float


@app.get("/sessions/{session_id}/cost")
def get_session_cost(session_id: str) -> SessionCost:
    """Sums every model_call log event tagged with this session_id (see
    timed_stream_chat) - the /cost command's data source. A conversation
    that only ever ran before this field existed sums to zero, not an
    error: there's nothing to attribute those older calls to."""
    calls = prompt_tokens = completion_tokens = 0
    cost_usd = 0.0
    if LOGS_FILE.exists():
        for line in LOGS_FILE.read_text().splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get("type") != "model_call" or event.get("session_id") != session_id:
                continue
            calls += 1
            prompt_tokens += event.get("prompt_tokens") or 0
            completion_tokens += event.get("completion_tokens") or 0
            cost_usd += event.get("cost_usd") or 0
    return SessionCost(
        calls=calls,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=round(cost_usd, 6),
    )


@app.get("/sessions/search")
def search_sessions(q: str) -> list[str]:
    """Returns ids of sessions whose title or message content contains q
    (case-insensitive). Reads each session file directly on the server
    rather than round-tripping every full history to the client just to
    filter them - titles are already searched client-side instantly, this
    only needs to cover message content. Declared before
    /sessions/{session_id} so "search" isn't swallowed as a session id."""
    query = q.strip().lower()
    if not query or not SESSIONS_DIR.exists():
        return []

    matches: list[str] = []
    for path in SESSIONS_DIR.glob("*.json"):
        session_id = path.stem
        try:
            messages = load_session(path)
        except (OSError, ValueError):
            continue
        for message in messages:
            content = message.get("content")
            if isinstance(content, str) and query in content.lower():
                matches.append(session_id)
                break
    return matches


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> list[dict[str, object]]:
    """Returns the raw message dicts as stored on disk. Typed loosely
    (not list[ChatCompletionMessageParam]) on purpose: that TypedDict-based
    return type made FastAPI's response serialization silently strip extra
    keys we stash on assistant messages (e.g. "model", used by the desktop
    app to show which model answered)."""
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    return cast(list[dict[str, object]], load_session(path))


def _message_text_and_attachments(content: object) -> tuple[str, list[str]]:
    """Plain text plus a short description per attachment, for a stored
    message's content - either a plain string, or a list of parts
    (text/image_url/file) once build_user_content added an attachment."""
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []
    text_parts: list[str] = []
    attachments: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text_parts.append(str(part.get("text", "")))
        elif part_type == "image_url":
            attachments.append("image jointe")
        elif part_type == "file":
            file_info = part.get("file")
            filename = (
                file_info.get("filename", "document") if isinstance(file_info, dict) else None
            )
            attachments.append(f"fichier joint : {filename or 'document'}")
    return "\n".join(text_parts), attachments


def export_session_as_markdown(messages: list[dict[str, object]], title: str) -> str:
    """Readable transcript for sharing/archiving outside sessions/ (not
    versioned, lives only on this machine) - one "---" per user turn, tool
    calls rendered as blockquotes under the assistant reply that made them."""
    tool_results: dict[str, str] = {}
    for m in messages:
        if m.get("role") != "tool":
            continue
        call_id, result = m.get("tool_call_id"), m.get("content")
        if isinstance(call_id, str) and isinstance(result, str):
            tool_results[call_id] = result

    lines = [f"# {title}", ""]
    first_turn = True
    for m in messages:
        role = m.get("role")
        if role in ("system", "tool"):
            continue

        if role == "user":
            if not first_turn:
                lines.extend(["---", ""])
            first_turn = False
            text, attachments = _message_text_and_attachments(m.get("content"))
            lines.extend(["**Vous**", ""])
            if text:
                lines.extend([text, ""])
            lines.extend(f"*[{a}]*" for a in attachments)
            if attachments:
                lines.append("")

        elif role == "assistant":
            model = m.get("model")
            header = f"**Triton** ({model})" if isinstance(model, str) and model else "**Triton**"
            lines.append(header)
            lines.append("")
            content = m.get("content")
            if isinstance(content, str) and content:
                lines.extend([content, ""])
            for tool_call in cast(list[object], m.get("tool_calls") or []):
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name", "?")
                args = function.get("arguments", "")
                result = tool_results.get(cast(str, tool_call.get("id", "")), "")
                lines.append(f"> 🔧 `{name}({args})`")
                if result:
                    preview = result if len(result) < 1000 else result[:1000] + "…"
                    lines.extend(f"> {line}" for line in preview.splitlines())
                lines.append("")

    return "\n".join(lines).rstrip() + "\n"


@app.get("/sessions/{session_id}/export")
def export_session(session_id: str, export_format: str = "markdown") -> Response:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session not found")
    messages = cast(list[dict[str, object]], load_session(path))
    title = load_title(session_id) or session_id

    if export_format == "json":
        content = json.dumps(messages, ensure_ascii=False, indent=2)
        media_type, filename = "application/json", f"{session_id}.json"
    else:
        content = export_session_as_markdown(messages, title)
        media_type, filename = "text/markdown", f"{session_id}.md"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    discard_snapshot(session_id)
    return {"ok": True}


class SnapshotInfo(BaseModel):
    kind: str
    created_at: str


@app.get("/sessions/{session_id}/snapshot")
def get_session_snapshot(session_id: str) -> SnapshotInfo:
    """Whether this session's project folder was auto-snapshotted before
    its first write (see tools/snapshot.py) - the desktop app uses this to
    decide whether to offer a "restore" action at all."""
    snapshot = get_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(404, "no snapshot for this session")
    return SnapshotInfo(kind=snapshot.kind, created_at=snapshot.created_at)


@app.post("/sessions/{session_id}/snapshot/restore")
def restore_session_snapshot(session_id: str) -> dict[str, bool]:
    """Undoes every write this session's tools made to its project folder,
    bringing it back to the state ensure_snapshot captured before the
    first one. Destructive (see tools/snapshot.py's restore_snapshot) -
    the desktop app is expected to confirm with the user before calling
    this, the same way it does for any other irreversible action."""
    snapshot = get_snapshot(session_id)
    if snapshot is None:
        raise HTTPException(404, "no snapshot for this session")

    project = get_project(snapshot.project_id)
    if project is None:
        raise HTTPException(404, "the project this snapshot belongs to no longer exists")

    try:
        restore_snapshot(project, snapshot)
    except RestoreError as e:
        raise HTTPException(500, f"restore failed: {e}") from e

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


@app.put("/projects/{project_id}")
def rename_project_endpoint(project_id: str, body: ProjectRename) -> list[Project]:
    if not rename_project(project_id, body.name):
        raise HTTPException(404, "project not found")
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


@app.get("/projects/{project_id}/file")
def get_project_file(project_id: str, path: str) -> FileResponse:
    """Serves one file's raw bytes for the desktop app's in-app viewer
    (PDF/HTML/Markdown preview - see ProjectFilePanel.tsx/FileViewerPanel.tsx),
    as an alternative to opening it with the OS's default app. `path` must
    resolve inside the project's folder - the same containment check
    enforce_project_sandbox uses for tool calls, applied here by hand since
    this endpoint takes a single free-form path, not a tool call's args."""
    project = get_project(project_id)
    if project is None:
        raise HTTPException(404, "project not found")

    root = Path(project.folder_path).resolve()
    target = Path(path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(403, "path resolves outside the project folder")
    if not target.is_file():
        raise HTTPException(404, "file not found")

    return FileResponse(target)


@app.get("/subagents")
def list_subagents() -> list[subagents.SubagentTask]:
    return subagents.list_tasks()


class OrchestratorDispatch(BaseModel):
    task: str
    session_id: str | None = None
    project_id: str | None = None


@app.post("/orchestrator")
def dispatch_orchestrator(body: OrchestratorDispatch) -> dict[str, str]:
    """Entry point for the /multi-agents slash command: resolves/creates a
    session exactly like /chat does (same title generation, same project
    attachment for a new session), saves the task as a normal user
    message, then dispatches the multi-agent run against that session -
    once it finishes, its own exchange is appended there too (see
    orchestrator._append_result_to_session), so the conversation reads
    seamlessly afterward instead of needing a separate view."""
    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    session_id = session_path.stem
    messages.append({"role": "user", "content": body.task})

    if is_new:
        save_title(session_id, generate_conversation_title(body.task))

    save_session(session_path, messages)

    project_id = load_session_project(session_id)
    run_id = orchestrator.dispatch(body.task, project_id=project_id, session_id=session_id)
    return {"run_id": run_id, "session_id": session_id}


@app.get("/orchestrator/{run_id}")
def get_orchestrator_run(run_id: str) -> orchestrator.OrchestratorRun:
    run = orchestrator.get(run_id)
    if run is None:
        raise HTTPException(404, "orchestrator run not found")
    return run


@app.get("/background_tasks")
def list_background_tasks_endpoint(session_id: str | None = None) -> list[dict[str, object]]:
    return [background_tasks.summary(t) for t in background_tasks.list_tasks(session_id)]


@app.get("/background_tasks/{task_id}")
def get_background_task(task_id: str) -> dict[str, object]:
    task = background_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "background task not found")
    return background_tasks.detail(task)


@app.post("/background_tasks/{task_id}/stop")
def stop_background_task_endpoint(task_id: str) -> dict[str, object]:
    task = background_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "background task not found")
    background_tasks.stop(task_id)
    return background_tasks.detail(task)


@app.delete("/background_tasks/{task_id}")
def delete_background_task_endpoint(task_id: str) -> dict[str, bool]:
    if background_tasks.get(task_id) is None:
        raise HTTPException(404, "background task not found")
    result = background_tasks.delete(task_id)
    if result.startswith("error:"):
        raise HTTPException(409, result)
    return {"deleted": True}


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
