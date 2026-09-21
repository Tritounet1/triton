import argparse
import json
import logging
import secrets
import sys
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from openai import APIError
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
from pydantic import BaseModel, Field
from scalar_fastapi import get_scalar_api_reference
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles

from triton import background_tasks, mcp_client
from triton.agents import orchestrator, subagents
from triton.backup import build_backup_zip
from triton.deployment import (
    DeploymentProfile,
    load_deployment_profile,
    load_web_auth_config,
    path_is_allowed,
    project_is_allowed,
    tool_is_allowed,
)
from triton.llm.api import (
    ChatResult,
    call_chat,
    generate_image,
    get_model,
    is_api_key_configured,
    is_transient_error,
)
from triton.llm.chat_loop import (
    MAX_ITERATIONS,
    build_system_message,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
    turn_start_indices,
)
from triton.llm.model_roles import ROLE_MODELS
from triton.paths import ROOT_DIR
from triton.storage import scheduled_tasks
from triton.storage.logs import LOGS_FILE, current_month_cost, events_for_month, log_event
from triton.storage.memory import append_global_memory, load_global_memory, set_global_memory
from triton.storage.projects import (
    Project,
    create_project,
    delete_project,
    get_project,
    load_project_memory,
    load_projects,
    rename_project,
    set_project_memory,
)
from triton.storage.sessions import (
    SESSIONS_DIR,
    allow_always,
    clear_session_project,
    delete_session,
    is_pinned,
    is_yolo_enabled,
    load_always_allowed,
    load_session,
    load_session_memory,
    load_session_model,
    load_session_project,
    load_title,
    new_session_path,
    save_session,
    save_session_model,
    save_session_project,
    save_title,
    set_pinned,
    set_session_memory,
    set_yolo_enabled,
)
from triton.storage.sessions import session_path as storage_session_path
from triton.storage.settings import (
    DEFAULT_MAX_SUBTASKS,
    MAX_MAX_SUBTASKS,
    load_image_model,
    load_max_subtasks,
    load_monthly_budget,
    load_role_model_overrides,
    save_image_model,
    save_max_subtasks,
    save_model,
    save_monthly_budget,
    save_multi_agent_roles,
    save_openrouter_api_key,
    save_role_model_override,
    save_tavily_api_key,
)
from triton.storage.snapshots import get_snapshot, list_snapshots
from triton.storage.web_accounts import (
    WebAccount,
    assign_session_owner,
    authenticate_web_account,
    initialize_web_accounts,
    owned_session_ids,
    session_is_owned_by,
)
from triton.tools import (
    SNAPSHOT_MAX_AGE_DAYS,
    TOOLS_REGISTRY,
    WRITE_TOOL_NAMES,
    InvalidSnapshotPathError,
    RestoreError,
    commit_diff_snapshot,
    commit_snapshot_file_content,
    diff_snapshot,
    discard_snapshot,
    discard_snapshots_for_project,
    enforce_project_sandbox,
    ensure_snapshot,
    finalize_snapshot,
    invoke_tool,
    is_skipped,
    is_tavily_configured,
    purge_expired_snapshots,
    restore_snapshot,
    snapshot_file_content,
    validate_snapshot_relative_path,
)
from triton.tools.memory import remember
from triton.web_runtime import SlidingWindowRateLimiter, load_web_runtime_config


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

# A packaged Tauri app gives its bundled sidecar a fresh token over stdin at
# launch. It protects the loopback API from a different local process that
# happens to bind port 8000 first. It stays optional for the CLI and Vite
# development workflow, which deliberately start server.py separately.
LOCAL_API_TOKEN: str | None = None
LOCAL_API_TOKEN_HEADER = "X-Triton-Local-Token"
DEPLOYMENT_PROFILE = load_deployment_profile()
WEB_AUTH_CONFIG = load_web_auth_config()
WEB_ADMIN_ACCOUNT: WebAccount | None = None
WEB_RUNTIME_CONFIG = load_web_runtime_config()
WEB_RATE_LIMITER = SlidingWindowRateLimiter(WEB_RUNTIME_CONFIG)
WEB_AUTH_PUBLIC_PATHS = {"/", "/auth/login", "/auth/session", "/health"}
WEB_FRONTEND_DIR = Path(__file__).resolve().parent / "app-desktop" / "dist"


def _session_file_path(session_id: str) -> Path:
    """Turns a route parameter into a safe session JSON path."""
    try:
        return storage_session_path(session_id)
    except ValueError as exc:
        raise HTTPException(400, "invalid session id") from exc


def _web_account_id(request: Request) -> str | None:
    account_id = request.session.get("web_account_id")
    return account_id if isinstance(account_id, str) else None


def _require_web_session_owner(request: Request, session_id: str) -> None:
    if DEPLOYMENT_PROFILE is not DeploymentProfile.WEB:
        return
    account_id = _web_account_id(request)
    if account_id is None or not session_is_owned_by(session_id, account_id):
        raise HTTPException(404, "session not found")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global WEB_ADMIN_ACCOUNT
    if DEPLOYMENT_PROFILE is DeploymentProfile.WEB and WEB_AUTH_CONFIG is not None:
        WEB_ADMIN_ACCOUNT = initialize_web_accounts(
            WEB_AUTH_CONFIG.username, WEB_AUTH_CONFIG.password
        )
        if SESSIONS_DIR.exists():
            for session_file in SESSIONS_DIR.glob("*.json"):
                assign_session_owner(session_file.stem, WEB_ADMIN_ACCOUNT.id)
    if DEPLOYMENT_PROFILE is DeploymentProfile.DESKTOP:
        mcp_client.manager.connect_all_enabled()
        resumed = orchestrator.resume_incomplete_runs()
        if resumed:
            logging.getLogger("uvicorn").info(
                "resumed %d orchestrator run(s) interrupted by the last restart: %s",
                len(resumed),
                ", ".join(resumed),
            )
        purged = purge_expired_snapshots()
        if purged:
            logging.getLogger("uvicorn").info(
                "purged %d snapshot(s) older than %d days", purged, SNAPSHOT_MAX_AGE_DAYS
            )
        scheduler_thread = threading.Thread(target=_scheduled_tasks_poll_loop, daemon=True)
        scheduler_thread.start()
    # Tauri waits for this message from the sidecar it spawned before it
    # gives the startup token to its WebView. Do not include the token in
    # the output: stdout may be copied to application logs.
    if LOCAL_API_TOKEN is not None:
        print("TRITON_SIDECAR_READY", flush=True)
    yield
    if DEPLOYMENT_PROFILE is DeploymentProfile.DESKTOP:
        _scheduler_stop_event.set()
        mcp_client.manager.disconnect_all()


# checked only while the backend happens to be running (no OS-level cron) -
# a few minutes' slack on exactly when a task fires is an acceptable
# tradeoff for not needing a real scheduler process. See
# storage/scheduled_tasks.py's own module docstring for the "no catch-up"
# design this poll loop relies on.
SCHEDULED_TASKS_POLL_INTERVAL_SECONDS = 60
SCHEDULED_TASKS_MAX_CONCURRENT = 2
_scheduler_stop_event = threading.Event()
_scheduled_task_slots = threading.BoundedSemaphore(SCHEDULED_TASKS_MAX_CONCURRENT)


def _run_scheduled_task(task: scheduled_tasks.ScheduledTask) -> None:
    """Resends a scheduled task's prompt into its own dedicated session
    (created once when the task was set up - see POST /scheduled_tasks)
    and drains run_chat_stream to completion. force_yolo=True: nobody is
    watching to answer a confirmation prompt for an unattended run, so
    without it every write/run_shell call would just sit until
    PENDING_CONFIRMATIONS' 300s timeout denies it by default."""
    try:
        session_path = storage_session_path(task.session_id)
    except ValueError:
        logging.getLogger("uvicorn").warning(
            "scheduled task %s has an invalid session id, skipping", task.id
        )
        return
    if not session_path.exists():
        logging.getLogger("uvicorn").warning(
            "scheduled task %s: session %s no longer exists, skipping",
            task.id,
            task.session_id,
        )
        return
    try:
        messages = load_session(session_path)
    except (OSError, ValueError):
        logging.getLogger("uvicorn").exception(
            "scheduled task %s: could not load session %s", task.id, task.session_id
        )
        return
    messages.append(cast(ChatCompletionMessageParam, {"role": "user", "content": task.prompt}))
    try:
        for _ in run_chat_stream(session_path, messages, force_yolo=True):
            pass
    except Exception:
        logging.getLogger("uvicorn").exception("scheduled task %s failed", task.id)


def _run_scheduled_task_worker(task: scheduled_tasks.ScheduledTask) -> None:
    """Runs one task outside the scheduler loop and always frees its slot."""
    try:
        _run_scheduled_task(task)
    finally:
        _scheduled_task_slots.release()


def _dispatch_due_scheduled_tasks(now: datetime) -> None:
    """Starts due tasks independently, with a small concurrency ceiling.

    A task may wait on the model or its stream timeout for a while. It must
    not hold up the poll loop (and therefore unrelated schedules), but an
    unbounded thread per due task would create a different availability
    problem. Tasks left due because both slots are occupied are retried on
    the next poll; they are intentionally not marked fired until dispatched.
    """
    for task in scheduled_tasks.due_tasks(now):
        if not _scheduled_task_slots.acquire(blocking=False):
            logging.getLogger("uvicorn").warning(
                "scheduled task %s delayed: all %d task slots are busy",
                task.id,
                SCHEDULED_TASKS_MAX_CONCURRENT,
            )
            continue
        scheduled_tasks.mark_fired(task.id, now)
        try:
            threading.Thread(
                target=_run_scheduled_task_worker,
                args=(task,),
                daemon=True,
                name=f"triton-scheduled-{task.id[:8]}",
            ).start()
        except Exception:
            _scheduled_task_slots.release()
            logging.getLogger("uvicorn").exception("scheduled task %s could not start", task.id)


def _scheduled_tasks_poll_loop() -> None:
    """Runs in its own daemon thread (started from lifespan), never as an
    asyncio task on the main event loop: run_chat_stream is a plain
    blocking generator (real network calls) - driving it directly on the
    event loop would stall every other request for as long as a task
    takes to run. Same threading.Thread pattern agents/subagents.py and
    agents/orchestrator.py already use for background agentic work."""
    while not _scheduler_stop_event.is_set():
        try:
            _dispatch_due_scheduled_tasks(datetime.now(UTC))
        except Exception:
            logging.getLogger("uvicorn").exception("scheduled task poll failed")
        _scheduler_stop_event.wait(SCHEDULED_TASKS_POLL_INTERVAL_SECONDS)


# route-grouping metadata for /docs (Swagger UI) and /redoc - purely
# cosmetic (FastAPI already serves both by default, docs_url/redoc_url
# aren't overridden anywhere), this just gives the desktop/CLI-free API
# consumer a readable grouped view instead of one flat list of 40+ routes.
# Order here is the order tags render in the UI.
OPENAPI_TAGS = [
    {"name": "Chat", "description": "Send a message, confirm/deny a tool call, cancel a reply."},
    {
        "name": "Sessions",
        "description": "Conversations: history, title, pin, per-session model override, "
        "cost, export, and the write-tool safety net's snapshot/restore.",
    },
    {"name": "Projects", "description": "Project folders: CRUD, file tree, raw file contents."},
    {
        "name": "Orchestrator",
        "description": "Multi-agent runs (the /multi-agents command): dispatch a task, poll "
        "its progress.",
    },
    {"name": "Subagents", "description": "Background research sub-agents (dispatch_subagent)."},
    {
        "name": "Background Tasks",
        "description": "Long-running processes started by the model (start_background_task).",
    },
    {"name": "MCP", "description": "Configured MCP servers: list, add, toggle, remove."},
    {
        "name": "Scheduled Tasks",
        "description": "Recurring prompts (hourly/daily/weekly), each resent into its own "
        "dedicated session by a poll loop that only runs while the backend is up - no "
        "catch-up for a missed occurrence, and no OS-level cron dependency.",
    },
    {
        "name": "Memory",
        "description": "The /remember global command's write path - the session/project "
        "tiers are written through the remember tool during a conversation instead, not a "
        "dedicated route.",
    },
    {"name": "Settings", "description": "Model, budget, API key, per-role model overrides."},
    {
        "name": "Backup",
        "description": "Full export of everything the harness manages under ROOT_DIR, as a "
        "single zip - for migrating to a new machine or as a safety net before a risky manual "
        "change.",
    },
    {"name": "Models", "description": "The OpenRouter model catalog."},
    {"name": "Images", "description": "Image generation and its OpenRouter model catalog."},
    {"name": "Logs", "description": "Raw event log (model/tool calls) for observability."},
    {"name": "Health", "description": "Liveness check."},
]

app = FastAPI(
    title="Triton API",
    description="Triton's HTTP/SSE API - everything the desktop app and CLI do goes through "
    "this, so it's usable directly (curl, scripts, another client) without either. POST /chat "
    "streams a Server-Sent Events response; every other route is plain JSON.",
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
    # Swagger UI's own default /docs is replaced below (Scalar instead) -
    # disable it here so the two don't collide on the same path.
    docs_url=None,
)


@app.middleware("http")
async def require_local_api_token(request: Request, call_next):
    started_at = time.perf_counter()
    response: Response | None = None
    try:
        if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
            content_length = request.headers.get("content-length")
            try:
                request_bytes = int(content_length) if content_length is not None else 0
            except ValueError:
                response = Response(
                    content='{"detail":"invalid content-length header"}',
                    media_type="application/json",
                    status_code=400,
                )
                return response
            if request_bytes > WEB_RUNTIME_CONFIG.max_request_bytes:
                response = Response(
                    content='{"detail":"request body exceeds the configured limit"}',
                    media_type="application/json",
                    status_code=413,
                )
                return response
            client_key = request.client.host if request.client else "unknown"
            retry_after = WEB_RATE_LIMITER.retry_after_seconds(client_key)
            if retry_after:
                response = Response(
                    content='{"detail":"rate limit exceeded"}',
                    headers={"Retry-After": str(retry_after)},
                    media_type="application/json",
                    status_code=429,
                )
                return response
        if not path_is_allowed(DEPLOYMENT_PROFILE, request.url.path):
            response = Response(
                content='{"detail":"this endpoint is unavailable in the web deployment profile"}',
                media_type="application/json",
                status_code=403,
            )
            return response
        # Let CORS answer preflight requests; the real request still needs the
        # token. Without this exception every browser request with our header
        # would be rejected before it could be sent.
        if LOCAL_API_TOKEN is not None and request.method != "OPTIONS":
            supplied_token = request.headers.get(LOCAL_API_TOKEN_HEADER, "")
            if not secrets.compare_digest(supplied_token, LOCAL_API_TOKEN):
                response = Response(
                    content='{"detail":"local API authentication failed"}',
                    media_type="application/json",
                    status_code=401,
                )
                return response
        if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
            if WEB_AUTH_CONFIG is None:
                response = Response(
                    content='{"detail":"web authentication is not configured"}',
                    media_type="application/json",
                    status_code=503,
                )
                return response
            is_public = request.url.path in WEB_AUTH_PUBLIC_PATHS or request.url.path.startswith(
                "/assets/"
            )
            if not is_public and not request.session.get("web_authenticated"):
                response = Response(
                    content='{"detail":"web authentication required"}',
                    media_type="application/json",
                    status_code=401,
                )
                return response
            session_path_parts = request.url.path.split("/")
            if (
                len(session_path_parts) > 2
                and session_path_parts[1] == "sessions"
                and session_path_parts[2] != "search"
            ):
                account_id = _web_account_id(request)
                if account_id is None or not session_is_owned_by(session_path_parts[2], account_id):
                    response = Response(
                        content='{"detail":"session not found"}',
                        media_type="application/json",
                        status_code=404,
                    )
                    return response
        response = await call_next(request)
        return response
    finally:
        if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
            logging.getLogger("uvicorn.error").info(
                json.dumps(
                    {
                        "type": "web_request",
                        "method": request.method,
                        "path": request.url.path,
                        "status_code": response.status_code if response else 500,
                        "duration_ms": round((time.perf_counter() - started_at) * 1000),
                    }
                )
            )


def _active_tool_schemas() -> list[ChatCompletionToolParam]:
    return [
        tool.schema
        for name, tool in TOOLS_REGISTRY.items()
        if tool_is_allowed(DEPLOYMENT_PROFILE, name)
    ]


def _require_profile_project_access(project_id: str | None) -> None:
    if not project_is_allowed(DEPLOYMENT_PROFILE, project_id):
        raise HTTPException(403, "projects are unavailable in the web deployment profile")


app.add_middleware(
    SessionMiddleware,
    secret_key=WEB_AUTH_CONFIG.session_secret if WEB_AUTH_CONFIG else secrets.token_urlsafe(32),
    https_only=(
        WEB_AUTH_CONFIG.secure_cookies
        if WEB_AUTH_CONFIG
        else DEPLOYMENT_PROFILE is DeploymentProfile.WEB
    ),
    same_site="lax",
    max_age=60 * 60 * 12,
)

app.mount("/assets", StaticFiles(directory=WEB_FRONTEND_DIR / "assets", check_dir=False))


# The API handles local files, conversations, and configured credentials, so
# it must never grant an arbitrary website browser access to localhost.  Keep
# CORS only for Triton's own Vite development server and Tauri's documented
# production origins (the protocol differs by platform/version).
TRITON_ALLOWED_ORIGINS = [
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=TRITON_ALLOWED_ORIGINS,
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
    # Only for this request: unlike /model, this is never persisted as the
    # conversation-wide override.
    model: str | None = None
    # 1-based turn index (same convention as turn_index_of/ensure_snapshot):
    # when set, the turn it points to and everything after it is dropped
    # before appending `message` as a fresh user turn - see
    # truncate_before_turn. Used for both editing an earlier message (the
    # client resends its new text) and regenerating the last response (the
    # client resends the same text unchanged): from the server's
    # perspective these are the same operation.
    edit_turn_index: int | None = None


class ConfirmRequest(BaseModel):
    confirmation_id: str
    approved: bool
    remember: bool = False


class ImageGenerateRequest(BaseModel):
    session_id: str | None = None
    prompt: str
    project_id: str | None = None
    attachments: list[Attachment] = []
    # Omit to use the dedicated global image setting; passing a value is a
    # one-shot choice that never alters that default.
    model: str | None = None


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
        path = _session_file_path(session_id)
        if path.exists():
            return path, load_session(path), False

    path = new_session_path()
    project = get_project(project_id) if project_id else None
    if project is not None:
        save_session_project(path.stem, project.id)
    return path, [build_system_message(path.stem, project)], True


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _is_tool_error(result: str) -> bool:
    """Same convention the frontend already infers a failed tool call
    from, with no separate structured status field (see App.tsx's
    toolCallStatus) - plus "unknown tool: ...", not in that convention
    (App.tsx never sees it happen live: the model hallucinating a tool
    name that isn't in TOOLS is exactly the kind of stuck-in-a-loop
    behavior MAX_CONSECUTIVE_TOOL_ERRORS exists to catch)."""
    return (
        result.startswith("error")
        or result.startswith("unknown tool:")
        or result.startswith("action denied")
    )


# stops the agentic loop once this many tool calls in a row have failed -
# the model repeating the same broken call is a much stronger "genuinely
# stuck" signal than a plain iteration count, and catches it long before
# MAX_ITERATIONS (deliberately generous - see chat_loop.py) would. Not
# reset per iteration: a failure streak spanning several separate model
# calls is exactly the case this exists to catch.
MAX_CONSECUTIVE_TOOL_ERRORS = 6

# same idea, for a reply with neither content nor a tool call (run_chat_stream's
# own "if reply.content is None" branch) - kept lower than
# MAX_CONSECUTIVE_TOOL_ERRORS since each attempt here is a full model
# round-trip (occasionally a slow one - a real one took 74s), not a cheap
# local check.
MAX_CONSECUTIVE_EMPTY_REPLIES = 4


def turn_index_of(messages: list[ChatCompletionMessageParam]) -> int:
    """Which turn `messages` is currently on (the nth "user" message,
    1-based) - the write-tool safety net's snapshot key (tools/snapshot.py's
    ensure_snapshot), so a restore point exists per turn instead of only
    once per session. Must be called on the full, uncompressed history:
    compress_history_if_needed can collapse several old turns into one
    system message, so counting *after* it runs would undercount real
    turns and collide two different turns onto the same snapshot."""
    return sum(1 for m in messages if m.get("role") == "user")


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
    force_yolo: bool = False,
    model_override: str | None = None,
) -> Iterator[str]:
    session_id = session_path.stem

    def emit(event: str, data: dict[str, object]) -> str:
        # every event tagged with the session it belongs to, so a client
        # that's switched away to a different conversation mid-stream can
        # tell this apart from whatever it's currently displaying instead
        # of blindly applying it (see App.tsx's sendMessage) - this is
        # what actually makes switching conversations while a response is
        # still streaming safe.
        return sse(event, {**data, "session_id": session_id})

    yield emit("session", {"session_id": session_id})

    if not is_api_key_configured():
        yield emit(
            "error",
            {
                "message": "Aucune clé API OpenRouter configurée. Ouvre les Paramètres "
                "(icône en bas de la barre latérale) pour en ajouter une.",
            },
        )
        return

    budget = load_monthly_budget()
    if budget is not None and current_month_cost() > budget:
        yield emit(
            "error",
            {
                "message": f"Budget mensuel de {budget:.2f} $ dépassé - nouveaux messages "
                "bloqués jusqu'au mois prochain. Augmente-le ou retire-le dans les Paramètres "
                "(Logs & coûts) pour continuer.",
            },
        )
        return

    project_id = load_session_project(session_id)
    project = get_project(project_id) if project_id else None
    session_model = model_override or load_session_model(session_id)
    # computed before compression can collapse old turns away - see
    # turn_index_of's own docstring
    turn_index = turn_index_of(messages)

    if first_message is not None:
        title = generate_conversation_title(first_message)
        save_title(session_path.stem, title)
        yield emit("title", {"title": title})

    compressed, compress_message = compress_history_if_needed(messages)
    messages[:] = compressed
    if compress_message:
        yield emit("info", {"message": compress_message})

    iteration = 0
    done = False
    cancelled = False
    # Le point "avant" est pris juste avant la premiere ecriture. Une fois
    # le tour termine, ce drapeau permet de capturer son etat final afin que
    # l'historique affiche un commit interne immuable, pas un diff du disque
    # courant qui change au fil du temps.
    turn_has_write = False
    consecutive_tool_errors = 0
    consecutive_empty_replies = 0

    while iteration < MAX_ITERATIONS and not done:
        if session_id in CANCELLED_SESSIONS:
            cancelled = True
            break
        iteration += 1
        content_parts: list[str] = []
        reply: ChatResult | None = None

        try:
            for event in timed_stream_chat(
                messages,
                tools=_active_tool_schemas(),
                model=session_model,
                session_id=session_id,
                project_id=project_id,
            ):
                if isinstance(event, str):
                    content_parts.append(event)
                    yield emit("token", {"text": event})
                else:
                    reply = event
        except APIError as exc:
            # llm/api.py's own retrying (_with_retry, and stream_chat's
            # own retry-if-nothing-produced-yet loop) already retried a
            # manifestly transient failure (network error, rate limit,
            # 5xx) a few times with backoff before giving up - this is
            # what reaches here: either that retry budget is exhausted, or
            # the failure happened after real content had already started
            # streaming out (unsafe to silently retry - see stream_chat's
            # own docstring), or it was never transient to begin with (bad
            # model name, invalid key...). Either way, surface it as a
            # normal chat error instead of letting it crash the SSE
            # response uncaught (which the client would just see as a
            # dropped connection, same as a genuine network failure on its
            # own end). The exception's own type name is included since
            # "l'appel au modèle a échoué" alone gives no way to tell a
            # one-off transient blip apart from a real, actionable one
            # (bad key, wrong model...) - logged too, for the same reason.
            log_event(
                type="model_call_error",
                error_type=type(exc).__name__,
                transient=is_transient_error(exc),
                message=str(exc),
            )
            yield emit(
                "error",
                {"message": f"l'appel au modèle a échoué ({type(exc).__name__}) : {exc}"},
            )
            done = True
            continue

        assert reply is not None

        if reply.tool_calls or reply.content is not None:
            consecutive_empty_replies = 0

        if reply.tool_calls:
            messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {
                        "role": "assistant",
                        "content": reply.content,
                        "tool_calls": to_tool_call_params(reply.tool_calls),
                        # A tool-call message is still a response from this
                        # model.  Persist it too: the desktop history uses
                        # this metadata to display the correct model avatar
                        # for a multi-step response, not Triton's fallback.
                        "model": reply.model,
                    },
                )
            )

            for tool_call in reply.tool_calls:
                if tool_call.type != "function":
                    continue

                name = tool_call.function.name
                duration = 0.0
                args: dict[str, object] = {}

                try:
                    try:
                        args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        result = f"error: invalid arguments ({tool_call.function.arguments})"
                    else:
                        sandbox_error = enforce_project_sandbox(name, args, project)
                        tool = TOOLS_REGISTRY.get(name)

                        # snapshot before the write actually runs, not after
                        # approval below - taking it is harmless even if this
                        # particular call ends up denied, and it guarantees the
                        # safety net is in place before any write from this
                        # turn could have landed (see tools/snapshot.py).
                        # ensure_snapshot's own return is only true the one time
                        # this specific turn's snapshot actually gets taken -
                        # surfaced here instead of only in the project file
                        # panel (SnapshotSection.tsx), which needed knowing the
                        # feature existed at all to go find.
                        if (
                            sandbox_error is None
                            and tool is not None
                            and name in WRITE_TOOL_NAMES
                            and ensure_snapshot(project, session_id, turn_index)
                        ):
                            yield emit(
                                "info",
                                {
                                    "message": "Point de restauration créé pour ce message : "
                                    "l'état actuel du dossier du projet vient d'être sauvegardé. "
                                    "Utilise /undo pour y revenir si besoin.",
                                },
                            )

                        if not tool_is_allowed(DEPLOYMENT_PROFILE, name):
                            result = f"error: {name} is unavailable in the web deployment profile"
                        elif sandbox_error is not None:
                            result = sandbox_error
                        elif tool is None:
                            result = f"unknown tool: {name}"
                        elif (
                            tool.read_only
                            or name in load_always_allowed(session_id)
                            or is_yolo_enabled(session_id)
                            or force_yolo
                        ):
                            if name in WRITE_TOOL_NAMES:
                                turn_has_write = True
                            result = invoke_tool(tool, name, args, session_id)
                        else:
                            confirmation_id = str(uuid.uuid4())
                            pending = PendingConfirmation()
                            PENDING_CONFIRMATIONS[confirmation_id] = pending

                            yield emit(
                                "confirmation_required",
                                {"confirmation_id": confirmation_id, "tool": name, "args": args},
                            )

                            got_response = pending.event.wait(timeout=300)
                            PENDING_CONFIRMATIONS.pop(confirmation_id, None)

                            if got_response and pending.approved:
                                if pending.remember:
                                    allow_always(session_id, name)
                                if name in WRITE_TOOL_NAMES:
                                    turn_has_write = True
                                result = invoke_tool(tool, name, args, session_id)
                            else:
                                result = "action denied by the user"
                except Exception as e:
                    # a bug anywhere else in this per-call handling (the
                    # sandbox check, the snapshot safety net, the
                    # confirmation wait...) must not silently kill the whole
                    # SSE stream - invoke_tool (_shared.py) already guards a
                    # tool's own fn(), same reasoning covers the plumbing
                    # around it: surface one failed tool call instead of the
                    # client just seeing a dropped connection with no
                    # feedback (found via a real report: a message sent,
                    # nothing comes back, not even an error).
                    result = f"error: unexpected failure handling {name} ({type(e).__name__}: {e})"

                yield emit(
                    "tool_call",
                    {"tool": name, "args": args, "result": result, "model": reply.model},
                )

                log_event(
                    type="tool_call",
                    tool=name,
                    args=args,
                    result_preview=result[:300],
                    result_chars=len(result),
                    duration_seconds=round(duration, 3),
                )

                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

                if _is_tool_error(result):
                    consecutive_tool_errors += 1
                    if consecutive_tool_errors >= MAX_CONSECUTIVE_TOOL_ERRORS:
                        yield emit(
                            "error",
                            {
                                "message": f"{consecutive_tool_errors} appels d'outils ont "
                                "échoué d'affilée - arrêt pour éviter une boucle bloquée "
                                "plutôt que de continuer à réessayer indéfiniment.",
                            },
                        )
                        done = True
                        break
                else:
                    consecutive_tool_errors = 0

            continue

        if reply.content is None:
            # a reasoning model can burn its whole output-token budget on
            # hidden reasoning and hit finish_reason == "length" with
            # nothing visible to show for it - but a provider can also
            # just return a genuinely empty completion (no content, no
            # tool call, often finish_reason == "stop", zero usage
            # reported) with no exception raised at all, so llm/api.py's
            # own retrying never sees it - found via a real conversation,
            # google/gemini-3.7-flash, twice in one session. Both are
            # recoverable the same way (nudge and let the loop retry) -
            # bounded by MAX_CONSECUTIVE_EMPTY_REPLIES so a model that's
            # genuinely stuck returning nothing doesn't retry silently
            # forever, each attempt a full (sometimes slow - one observed
            # case took 74s) round-trip.
            consecutive_empty_replies += 1
            if consecutive_empty_replies > MAX_CONSECUTIVE_EMPTY_REPLIES:
                yield emit(
                    "error",
                    {
                        "message": f"the model returned an empty response "
                        f"{consecutive_empty_replies} times in a row - giving up "
                        "instead of continuing to retry.",
                    },
                )
                done = True
                continue
            if reply.finish_reason == "length":
                yield emit(
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
            else:
                yield emit(
                    "info",
                    {
                        "message": "the model returned an empty response - asking it to "
                        f"continue (attempt {consecutive_empty_replies}/"
                        f"{MAX_CONSECUTIVE_EMPTY_REPLIES}).",
                    },
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "Your last response was empty - no text, no tool call. "
                        "Please continue.",
                    }
                )
            continue

        messages.append(
            cast(
                ChatCompletionMessageParam,
                {"role": "assistant", "content": reply.content, "model": reply.model},
            )
        )
        yield emit(
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
        yield emit("error", {"message": f"limit of {MAX_ITERATIONS} iterations reached."})

    if turn_has_write and finalize_snapshot(project, session_id, turn_index):
        yield emit(
            "info",
            {
                "message": "Sauvegarde interne finalisée : ce changement peut maintenant être "
                "restauré depuis l'historique.",
            },
        )

    save_session(session_path, messages)


@app.get("/", include_in_schema=False)
def root() -> Response:
    if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
        index_path = WEB_FRONTEND_DIR / "index.html"
        if not index_path.is_file():
            raise HTTPException(503, "the web client has not been built")
        return FileResponse(index_path)
    """Visiting the API's own base URL in a browser is far more likely to
    be someone looking for the docs than expecting a 404 - send them
    there instead."""
    return RedirectResponse("/docs")


@app.get("/docs", include_in_schema=False)
def scalar_docs() -> HTMLResponse:
    """Scalar instead of FastAPI's default Swagger UI at /docs (disabled
    via docs_url=None above) - same OpenAPI schema (/openapi.json,
    unaffected), a nicer-looking, more legible page around it. Loads its
    JS from a CDN (jsdelivr) by default, same as Swagger UI's own assets
    normally would - both need network access to render, this isn't a new
    requirement. /redoc (FastAPI's own, untouched) stays as a lighter,
    read-only alternative."""
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
        dark_mode=True,
    )


@app.get("/health", tags=["Health"])
def health() -> dict[str, bool | str]:
    return {"ok": True, "model": get_model()}


class WebLoginRequest(BaseModel):
    username: str
    password: str


@app.get("/auth/session", tags=["Health"])
def web_session(request: Request) -> dict[str, bool]:
    return {"authenticated": bool(request.session.get("web_authenticated"))}


@app.post("/auth/login", tags=["Health"])
def web_login(body: WebLoginRequest, request: Request) -> dict[str, bool]:
    config = WEB_AUTH_CONFIG
    if DEPLOYMENT_PROFILE is not DeploymentProfile.WEB or config is None:
        raise HTTPException(404, "web authentication is unavailable")
    account = authenticate_web_account(body.username, body.password)
    if account is None:
        raise HTTPException(401, "invalid credentials")
    request.session.clear()
    request.session["web_authenticated"] = True
    request.session["web_account_id"] = account.id
    request.session["web_role"] = account.role
    return {"ok": True}


@app.post("/auth/logout", tags=["Health"])
def web_logout(request: Request) -> dict[str, bool]:
    request.session.clear()
    return {"ok": True}


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


class ImageModelInfo(TypedDict):
    id: str
    name: str
    description: str


@app.get("/settings/model", tags=["Settings"])
def get_current_model() -> dict[str, str]:
    return {"model": get_model()}


@app.put("/settings/model", tags=["Settings"])
def set_current_model(body: ModelUpdate) -> dict[str, str]:
    save_model(body.model)
    return {"model": body.model}


@app.get("/settings/image_model", tags=["Settings"])
def get_current_image_model() -> dict[str, str]:
    return {"model": load_image_model()}


@app.put("/settings/image_model", tags=["Settings"])
def set_current_image_model(body: ModelUpdate) -> dict[str, str]:
    save_image_model(body.model)
    return {"model": body.model}


@app.get("/settings/budget", tags=["Settings"])
def get_monthly_budget() -> dict[str, float | None]:
    return {"monthly_budget_usd": load_monthly_budget()}


@app.put("/settings/budget", tags=["Settings"])
def set_monthly_budget(body: BudgetUpdate) -> dict[str, float | None]:
    save_monthly_budget(body.monthly_budget_usd)
    return {"monthly_budget_usd": body.monthly_budget_usd}


class BudgetStatus(BaseModel):
    monthly_budget_usd: float | None
    spent_usd: float
    exceeded: bool


@app.get("/settings/budget/status", tags=["Settings"])
def get_budget_status() -> BudgetStatus:
    """The single source of truth for "is the monthly budget exceeded" -
    the same current_month_cost() run_chat_stream/dispatch_orchestrator
    actually gate new calls on, rather than a client recomputing its own
    version from raw /logs events (which could drift from what's really
    being enforced, e.g. by missing an event type)."""
    budget = load_monthly_budget()
    spent = current_month_cost()
    return BudgetStatus(
        monthly_budget_usd=budget,
        spent_usd=spent,
        exceeded=budget is not None and spent > budget,
    )


@app.get("/backup/export", tags=["Backup"])
def export_backup() -> Response:
    """Everything the harness manages under ROOT_DIR (sessions, projects,
    memory, snapshots, MCP server configs, settings...) as a single zip -
    see triton/backup.py. Includes API keys as-is (settings.json,
    mcp_servers.json, .env) - the desktop app warns about this before the
    download starts (BackupSettings.tsx), this endpoint itself doesn't
    redact anything."""
    data = build_backup_zip()
    filename = f"triton-backup-{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ApiKeyUpdate(BaseModel):
    api_key: str


@app.get("/settings/api_key", tags=["Settings"])
def get_api_key_status() -> dict[str, bool]:
    # never echoes the key itself back, only whether one is configured -
    # the Settings UI shows a blank password field either way, never the
    # real value once saved.
    return {"configured": is_api_key_configured()}


@app.put("/settings/api_key", tags=["Settings"])
def set_api_key(body: ApiKeyUpdate) -> dict[str, bool]:
    save_openrouter_api_key(body.api_key.strip() or None)
    return {"configured": is_api_key_configured()}


class TavilyKeyUpdate(BaseModel):
    api_key: str


@app.get("/settings/tavily_key", tags=["Settings"])
def get_tavily_key_status() -> dict[str, bool]:
    """Unlike OpenRouter's key, Tavily is optional - web_search falls back
    to scraping DuckDuckGo when this isn't configured (see tools/web.py),
    it's never a hard blocker like a missing OpenRouter key is."""
    return {"configured": is_tavily_configured()}


@app.put("/settings/tavily_key", tags=["Settings"])
def set_tavily_key(body: TavilyKeyUpdate) -> dict[str, bool]:
    save_tavily_api_key(body.api_key.strip() or None)
    return {"configured": is_tavily_configured()}


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


@app.get("/settings/role_models", tags=["Settings"])
def get_role_models() -> list[RoleModelInfo]:
    return _role_models_status()


@app.put("/settings/role_models", tags=["Settings"])
def set_role_model(body: RoleModelUpdate) -> list[RoleModelInfo]:
    if body.role not in ROLE_MODELS:
        raise HTTPException(404, f"unknown role: {body.role}")
    save_role_model_override(body.role, body.model)
    return _role_models_status()


class MaxSubtasksUpdate(BaseModel):
    # None clears the override, falling back to DEFAULT_MAX_SUBTASKS again
    value: int | None = None


@app.get("/settings/max_subtasks", tags=["Settings"])
def get_max_subtasks() -> dict[str, int]:
    return {"value": load_max_subtasks(), "default": DEFAULT_MAX_SUBTASKS, "max": MAX_MAX_SUBTASKS}


@app.put("/settings/max_subtasks", tags=["Settings"])
def set_max_subtasks(body: MaxSubtasksUpdate) -> dict[str, int]:
    if body.value is not None and not (1 <= body.value <= MAX_MAX_SUBTASKS):
        raise HTTPException(400, f"value must be between 1 and {MAX_MAX_SUBTASKS}")
    save_max_subtasks(body.value)
    return {"value": load_max_subtasks(), "default": DEFAULT_MAX_SUBTASKS, "max": MAX_MAX_SUBTASKS}


class MultiAgentRoleModel(BaseModel):
    id: str
    label: str
    description: str
    can_write: bool = False
    system_prompt: str = ""


def _roles_status() -> list[MultiAgentRoleModel]:
    return [
        MultiAgentRoleModel(
            id=r.id,
            label=r.label,
            description=r.description,
            can_write=r.can_write,
            system_prompt=r.system_prompt,
        )
        for r in orchestrator.load_roles()
    ]


@app.get("/settings/multi_agent_roles", tags=["Settings"])
def get_multi_agent_roles() -> list[MultiAgentRoleModel]:
    """The multi-agent orchestrator's configured role set - DEFAULT_ROLES
    (code/research/vision/conversational) unless the Settings UI has saved
    a custom list. Each role's `id` also keys its entry in
    /settings/role_models (which model runs it) - see orchestrator.py's
    MultiAgentRole docstring for what changing an id in place vs.
    removing/adding one means for anything already referencing it."""
    return _roles_status()


class MultiAgentRolesUpdate(BaseModel):
    roles: list[MultiAgentRoleModel]


@app.put("/settings/multi_agent_roles", tags=["Settings"])
def set_multi_agent_roles(body: MultiAgentRolesUpdate) -> list[MultiAgentRoleModel]:
    if not body.roles:
        raise HTTPException(400, "at least one role is required")
    ids = [r.id.strip() for r in body.roles]
    if any(not i for i in ids):
        raise HTTPException(400, "every role needs a non-empty id")
    if len(set(ids)) != len(ids):
        raise HTTPException(400, "role ids must be unique")

    save_multi_agent_roles([r.model_dump() for r in body.roles])
    return _roles_status()


@app.post("/settings/multi_agent_roles/reset", tags=["Settings"])
def reset_multi_agent_roles() -> list[MultiAgentRoleModel]:
    save_multi_agent_roles(None)
    return _roles_status()


# short-lived: the catalog itself barely changes minute to minute, but a
# short TTL still means the desktop app's own startup (modelsCatalog in
# App.tsx) and every time Settings > Modele is opened don't each cost a
# fresh round-trip to OpenRouter - see pricing.py's get_price() for the
# same cache-with-TTL shape, kept separate since that one only needs
# prompt/completion price per model, not this endpoint's fuller shape.
_MODELS_CACHE_TTL_SECONDS = 300
_models_cache: list[ModelInfo] | None = None
_models_cache_time = 0.0
_image_models_cache: list[ImageModelInfo] | None = None
_image_models_cache_time = 0.0


@app.get("/openrouter/models", tags=["Models"])
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
        # ":batch" variants (e.g. "openai/gpt-6-astra:batch") are OpenRouter's
        # async, delayed-response tier - meant for bulk offline processing,
        # not a fit for this harness's synchronous chat loop. Filtered here
        # (the single source every model picker in the desktop app reads
        # from) rather than in each picker separately.
        if m["id"].endswith(":batch"):
            continue
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


@app.get("/openrouter/image-models", tags=["Models"])
def list_openrouter_image_models() -> list[ImageModelInfo]:
    """Lists image-generation models from OpenRouter's separate catalog."""
    global _image_models_cache, _image_models_cache_time

    cache_age = time.monotonic() - _image_models_cache_time
    if _image_models_cache is not None and cache_age < _MODELS_CACHE_TTL_SECONDS:
        return _image_models_cache

    try:
        resp = requests.get("https://openrouter.ai/api/v1/images/models", timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        if _image_models_cache is not None:
            return _image_models_cache
        raise HTTPException(502, f"could not reach OpenRouter ({exc})") from exc

    models: list[ImageModelInfo] = []
    for item in resp.json().get("data", []):
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        name = item.get("name")
        description = item.get("description")
        models.append(
            {
                "id": model_id,
                "name": name if isinstance(name, str) and name else model_id,
                "description": description if isinstance(description, str) else "",
            }
        )
    _image_models_cache = models
    _image_models_cache_time = time.monotonic()
    return models


# images and PDFs only: other file types are handled inconsistently across
# providers (some accept arbitrary documents, most don't), whereas these two
# map to well-defined OpenAI-compatible content parts (image_url and
# OpenRouter's file) that every model advertising the matching input
# modality accepts.
MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024
# A request with many individually-valid attachments could otherwise still
# allocate tens or hundreds of MB before reaching the provider. Keep enough
# room for two high-resolution files while bounding request memory/network.
MAX_TOTAL_ATTACHMENT_BYTES = 16 * 1024 * 1024


def validate_attachments(attachments: list[Attachment]) -> None:
    total_bytes = 0
    for a in attachments:
        is_image_or_pdf = a.data_url.startswith(("data:image/", "data:application/pdf"))
        if not is_image_or_pdf:
            raise HTTPException(400, f"attachment {a.name!r} is not a supported image or PDF")
        _, _, b64_payload = a.data_url.partition(",")
        attachment_bytes = len(b64_payload) * 3 // 4
        if attachment_bytes > MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                400,
                f"attachment {a.name!r} exceeds the "
                f"{MAX_ATTACHMENT_BYTES // (1024 * 1024)}MB limit",
            )
        total_bytes += attachment_bytes
        if total_bytes > MAX_TOTAL_ATTACHMENT_BYTES:
            raise HTTPException(
                400,
                "attachments exceed the total "
                f"{MAX_TOTAL_ATTACHMENT_BYTES // (1024 * 1024)}MB request limit",
            )


def validate_image_references(attachments: list[Attachment]) -> None:
    """The Images API takes reference images, never PDFs or other files."""
    validate_attachments(attachments)
    if len(attachments) > 8:
        raise HTTPException(400, "at most 8 image references are supported")
    for attachment in attachments:
        if not attachment.data_url.startswith("data:image/"):
            raise HTTPException(400, "image generation references must be images")


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


def truncate_before_turn(
    messages: list[ChatCompletionMessageParam], turn_index: int
) -> list[ChatCompletionMessageParam]:
    """Drops the user message that starts `turn_index` (1-based, same
    convention as turn_index_of/ensure_snapshot) and everything after it -
    used by POST /chat's edit_turn_index (edit/regenerate) to discard a
    turn before resending it. Snapshots already taken for that turn_index
    (tools/snapshot.py's ensure_snapshot) are left as-is: they still
    describe the project's state right before this turn, which stays
    correct no matter how many times the turn itself gets redone."""
    starts = turn_start_indices(messages)
    if turn_index < 1 or turn_index > len(starts):
        raise HTTPException(400, f"invalid edit_turn_index: {turn_index}")
    return messages[: starts[turn_index - 1]]


@app.post("/chat", tags=["Chat"])
def chat(body: ChatRequest, request: Request) -> StreamingResponse:
    _require_profile_project_access(body.project_id)
    validate_attachments(body.attachments)
    if body.session_id:
        _require_web_session_owner(request, body.session_id)
    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    if is_new and DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
        account_id = _web_account_id(request)
        if account_id is None:
            raise HTTPException(401, "web authentication required")
        assign_session_owner(session_path.stem, account_id)
    if body.edit_turn_index is not None:
        messages = truncate_before_turn(messages, body.edit_turn_index)
    messages.append(
        cast(
            ChatCompletionMessageParam,
            {"role": "user", "content": build_user_content(body.message, body.attachments)},
        )
    )

    stream_kwargs: dict[str, object] = {"first_message": body.message if is_new else None}
    # Keep the legacy no-override call shape too: a few integrations and
    # tests intentionally replace run_chat_stream with the original small
    # signature, and no model argument is needed in the normal path.
    if body.model:
        stream_kwargs["model_override"] = body.model
    return StreamingResponse(
        run_chat_stream(session_path, messages, **stream_kwargs),  # type: ignore[arg-type]
        media_type="text/event-stream",
    )


@app.post("/images/generate", tags=["Images"])
def generate_conversation_image(body: ImageGenerateRequest) -> dict[str, object]:
    """Generates an image and persists it as an assistant message.

    The data URL and the producing model live in the regular session JSON,
    so a reload keeps both the image and its correct model avatar.
    """
    _require_profile_project_access(body.project_id)
    prompt = body.prompt.strip()
    if not prompt:
        raise HTTPException(400, "image prompt must not be empty")
    if len(prompt) > 12_000:
        raise HTTPException(400, "image prompt exceeds 12000 characters")
    validate_image_references(body.attachments)
    if not is_api_key_configured():
        raise HTTPException(400, "Aucune clé API OpenRouter configurée.")
    budget = load_monthly_budget()
    if budget is not None and current_month_cost() > budget:
        raise HTTPException(403, "Budget mensuel dépassé - génération bloquée.")

    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    messages.append(
        cast(
            ChatCompletionMessageParam,
            {"role": "user", "content": build_user_content(prompt, body.attachments)},
        )
    )
    try:
        result = generate_image(
            prompt,
            body.model,
            [attachment.data_url for attachment in body.attachments],
        )
    except (RuntimeError, ValueError) as exc:
        log_event(
            type="image_generation_error",
            model=body.model or load_image_model(),
            message=str(exc),
        )
        raise HTTPException(502, str(exc)) from exc

    messages.append(
        cast(
            ChatCompletionMessageParam,
            {
                "role": "assistant",
                "content": "",
                "model": result.model,
                "generated_images": result.images,
            },
        )
    )
    save_session(session_path, messages)

    title: str | None = None
    if is_new:
        title = prompt[:MAX_TITLE_CHARS].rstrip()
        if len(prompt) > MAX_TITLE_CHARS:
            title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
        save_title(session_path.stem, title)

    log_event(
        type="image_generation",
        session_id=session_path.stem,
        project_id=body.project_id,
        model=result.model,
        prompt_chars=len(prompt),
        reference_count=len(body.attachments),
        image_count=len(result.images),
    )
    return {
        "session_id": session_path.stem,
        "title": title,
        "model": result.model,
        "images": result.images,
    }


@app.post("/chat/confirm", tags=["Chat"])
def confirm(body: ConfirmRequest) -> dict[str, bool]:
    pending = PENDING_CONFIRMATIONS.get(body.confirmation_id)
    if pending is None:
        raise HTTPException(404, "unknown or already-processed confirmation")

    pending.approved = body.approved
    pending.remember = body.remember
    pending.event.set()
    return {"ok": True}


@app.post("/chat/cancel", tags=["Chat"])
def cancel_chat(body: CancelRequest) -> dict[str, bool]:
    """Marks a session as cancelled: run_chat_stream checks this between
    agentic-loop iterations and stops before starting another one. Doesn't
    interrupt a model call already in flight (see the client-side abort,
    which closes the connection those tokens are streamed to)."""
    CANCELLED_SESSIONS.add(body.session_id)
    return {"ok": True}


@app.get("/sessions", tags=["Sessions"])
def list_sessions(request: Request) -> list[dict[str, str | bool | None]]:
    if not SESSIONS_DIR.exists():
        return []
    ids = sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))
    if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
        account_id = _web_account_id(request)
        ids = sorted(owned_session_ids(account_id)) if account_id else []
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


@app.put("/sessions/{session_id}/pin", tags=["Sessions"])
def pin_session(session_id: str, body: PinRequest) -> dict[str, bool]:
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    set_pinned(session_id, body.pinned)
    return {"ok": True}


@app.get("/sessions/{session_id}/yolo", tags=["Sessions"])
def get_session_yolo(session_id: str) -> dict[str, bool]:
    """Whether the /yolo command is active for this conversation (see
    is_yolo_enabled) - the desktop app reads this on session switch/load
    to show a persistent warning, not just a one-off toast when toggled,
    since it silently changes what every following message does."""
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    return {"enabled": is_yolo_enabled(session_id)}


@app.post("/sessions/{session_id}/yolo", tags=["Sessions"])
def toggle_session_yolo(session_id: str) -> dict[str, bool]:
    """The /yolo command's backend: toggles whether this conversation
    skips the confirmation prompt for every non-read-only tool call (see
    run_chat_stream's own check) - running /yolo again turns it back off,
    no separate command for that. Doesn't touch enforce_project_sandbox
    at all: a project-less conversation, a path outside the project,
    ROOT_DIR... all stay blocked exactly as before, this only ever
    removes the confirmation step itself."""
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    enabled = not is_yolo_enabled(session_id)
    set_yolo_enabled(session_id, enabled)
    return {"enabled": enabled}


class ModelRequest(BaseModel):
    model: str


@app.get("/sessions/{session_id}/model", tags=["Sessions"])
def get_session_model(session_id: str) -> dict[str, str | None]:
    """The /model command's override for this conversation, if any (see
    load_session_model) - None means it's using the global default
    (GET /settings/model), like every conversation before this existed."""
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    return {"model": load_session_model(session_id)}


@app.put("/sessions/{session_id}/model", tags=["Sessions"])
def set_session_model(session_id: str, body: ModelRequest) -> dict[str, str]:
    path = _session_file_path(session_id)
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


@app.get("/sessions/{session_id}/cost", tags=["Sessions"])
def get_session_cost(session_id: str) -> SessionCost:
    """Sums every model_call log event tagged with this session_id (see
    timed_stream_chat) - the /cost command's data source. A conversation
    that only ever ran before this field existed sums to zero, not an
    error: there's nothing to attribute those older calls to."""
    _session_file_path(session_id)
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


class RememberRequest(BaseModel):
    note: str


@app.post("/sessions/{session_id}/remember", tags=["Sessions"])
def remember_in_session(session_id: str, body: RememberRequest) -> dict[str, str]:
    """The /remember session command's backend - reuses the remember tool
    itself (tools/memory.py) rather than duplicating its project-vs-session
    scoping logic, so this lands in exactly the same place a model-issued
    remember call for this session would."""
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    return {"result": remember(body.note, session_id=session_id)}


@app.post("/sessions/{session_id}/compact", tags=["Sessions"])
def compact_session(session_id: str) -> dict[str, str]:
    """The /compact command's backend - forces compress_history_if_needed
    to summarize the oldest turns right now, instead of waiting for the
    automatic trigger in run_chat_stream (context already over
    MAX_CONTEXT_CHARS). Saves the compressed history back so it's what the
    next turn (and the next automatic check) build on."""
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")

    messages = load_session(path)
    compressed, compress_message = compress_history_if_needed(messages, force=True)
    if compress_message is None:
        return {"result": "nothing to compact yet: not enough exchanges in this conversation"}

    save_session(path, compressed)
    return {"result": compress_message}


@app.post("/memory/global", tags=["Memory"])
def remember_globally(body: RememberRequest) -> dict[str, str]:
    """The /remember global command's backend - the only writer of
    memory_global.md (see storage/memory.py): the remember tool itself
    never writes here, only ever to the session/project tier."""
    append_global_memory(body.note)
    return {"result": f"remembered globally: {body.note.strip()}"}


class MemoryContent(BaseModel):
    content: str


# GET/PUT below power the memory browser (MemorySettings.tsx): unlike the
# POST endpoints above (and the remember tool itself), which only ever
# append one note, these read/overwrite the raw file - letting the user
# see and edit/delete what's been remembered instead of having to open
# memory_global.md/project_memory/*.md by hand.


@app.get("/memory/global", tags=["Memory"])
def get_global_memory() -> MemoryContent:
    return MemoryContent(content=load_global_memory())


@app.put("/memory/global", tags=["Memory"])
def put_global_memory(body: MemoryContent) -> MemoryContent:
    set_global_memory(body.content)
    return body


@app.get("/projects/{project_id}/memory", tags=["Memory"])
def get_project_memory(project_id: str) -> MemoryContent:
    if get_project(project_id) is None:
        raise HTTPException(404, "project not found")
    return MemoryContent(content=load_project_memory(project_id))


@app.put("/projects/{project_id}/memory", tags=["Memory"])
def put_project_memory(project_id: str, body: MemoryContent) -> MemoryContent:
    if get_project(project_id) is None:
        raise HTTPException(404, "project not found")
    set_project_memory(project_id, body.content)
    return body


@app.get("/sessions/{session_id}/memory", tags=["Memory"])
def get_session_memory(session_id: str) -> MemoryContent:
    if not _session_file_path(session_id).exists():
        raise HTTPException(404, "session not found")
    return MemoryContent(content=load_session_memory(session_id))


@app.put("/sessions/{session_id}/memory", tags=["Memory"])
def put_session_memory(session_id: str, body: MemoryContent) -> MemoryContent:
    if not _session_file_path(session_id).exists():
        raise HTTPException(404, "session not found")
    set_session_memory(session_id, body.content)
    return body


@app.get("/sessions/search", tags=["Sessions"])
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


@app.get("/sessions/{session_id}", tags=["Sessions"])
def get_session(session_id: str) -> list[dict[str, object]]:
    """Returns the raw message dicts as stored on disk. Typed loosely
    (not list[ChatCompletionMessageParam]) on purpose: that TypedDict-based
    return type made FastAPI's response serialization silently strip extra
    keys we stash on assistant messages (e.g. "model", used by the desktop
    app to show which model answered)."""
    path = _session_file_path(session_id)
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


@app.get("/sessions/{session_id}/export", tags=["Sessions"])
def export_session(session_id: str, export_format: str = "markdown") -> Response:
    path = _session_file_path(session_id)
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


@app.put("/sessions/{session_id}/title", tags=["Sessions"])
def rename_session(session_id: str, body: RenameRequest) -> dict[str, bool]:
    path = _session_file_path(session_id)
    if not path.exists():
        raise HTTPException(404, "session not found")
    save_title(session_id, body.title)
    return {"ok": True}


@app.delete("/sessions/{session_id}", tags=["Sessions"])
def remove_session(session_id: str) -> dict[str, bool]:
    _session_file_path(session_id)
    if not delete_session(session_id):
        raise HTTPException(404, "session not found")
    discard_snapshot(session_id)
    return {"ok": True}


MESSAGE_PREVIEW_CHARS = 80


def _user_message_preview(session_id: str, turn_index: int) -> str | None:
    """The text of the nth user message in a session (1-based) - labels a
    restore point with what it precedes ("before: ...") instead of a bare
    turn number, so picking one to restore to is actually meaningful.
    None if the session/message is gone, or that message was purely an
    attachment with no text part."""
    try:
        path = storage_session_path(session_id)
    except ValueError:
        return None
    if not path.exists():
        return None
    try:
        messages = load_session(path)
    except (OSError, ValueError):
        return None

    user_messages = [m for m in messages if m.get("role") == "user"]
    if turn_index < 1 or turn_index > len(user_messages):
        return None

    content = user_messages[turn_index - 1].get("content")
    text: str | None = content if isinstance(content, str) else None
    if text is None and isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = cast("str | None", part.get("text"))
                break
    if not text:
        return None

    text = text.strip()
    if len(text) > MESSAGE_PREVIEW_CHARS:
        text = text[:MESSAGE_PREVIEW_CHARS].rstrip() + "..."
    return text


class SnapshotPoint(BaseModel):
    turn_index: int
    kind: str
    created_at: str
    message_preview: str | None
    # Les nouveaux points ont un etat "apres" scelle a la fin du tour et
    # peuvent donc etre presentes comme des commits internes fiables.
    has_final_state: bool


@app.get("/sessions/{session_id}/snapshots", tags=["Sessions"])
def list_session_snapshots(session_id: str) -> list[SnapshotPoint]:
    """Every restore point this session has - one per turn whose first
    write triggered a snapshot (see tools/snapshot.py's ensure_snapshot),
    oldest first. Empty rather than a 404 when there are none: the
    desktop app uses an empty list the same way it used to use a 404, to
    decide whether to offer a restore action at all."""
    _session_file_path(session_id)
    return [
        SnapshotPoint(
            turn_index=s.turn_index,
            kind=s.kind,
            created_at=s.created_at,
            message_preview=_user_message_preview(session_id, s.turn_index),
            has_final_state=s.after_location is not None,
        )
        for s in list_snapshots(session_id)
    ]


class SnapshotDiffResponse(BaseModel):
    created: list[str]
    deleted: list[str]
    modified: list[str]


@app.get("/sessions/{session_id}/snapshot/diff", tags=["Sessions"])
def get_session_snapshot_diff(
    session_id: str,
    turn_index: int,
    view: Literal["rollback", "commit"] = "rollback",
) -> SnapshotDiffResponse:
    """A preview of what restoring to this specific turn's snapshot would
    actually change - which files it created (restore deletes them),
    deleted (restore recreates them), or modified (restore reverts them).
    The desktop app fetches this when a restore confirmation dialog
    opens for that turn, not eagerly for every restore point on session
    load - it's real work (hashing every file currently in the project
    to compare against the snapshot's manifest - see
    triton/tools/snapshot.py) that only matters right before the user is
    about to commit to it."""
    _session_file_path(session_id)
    snapshot = get_snapshot(session_id, turn_index)
    if snapshot is None:
        raise HTTPException(404, "no snapshot for this session at that turn")

    project = get_project(snapshot.project_id)
    if project is None:
        raise HTTPException(404, "the project this snapshot belongs to no longer exists")

    try:
        diff = (
            commit_diff_snapshot(snapshot) if view == "commit" else diff_snapshot(project, snapshot)
        )
    except RestoreError as e:
        raise HTTPException(500, f"could not compute diff: {e}") from e

    return SnapshotDiffResponse(created=diff.created, deleted=diff.deleted, modified=diff.modified)


class SnapshotFileContentResponse(BaseModel):
    old: str | None
    new: str | None


@app.get("/sessions/{session_id}/snapshot/file", tags=["Sessions"])
def get_session_snapshot_file(
    session_id: str,
    turn_index: int,
    path: str,
    view: Literal["rollback", "commit"] = "rollback",
) -> SnapshotFileContentResponse:
    """Before/after text content for one file changed by this turn (see
    GET .../snapshot/diff for the list of changed paths) - powers the
    restore-history browser's per-file diff view (SnapshotHistoryView.tsx).
    `path` is relative to the project folder, exactly as it appears in the
    diff response."""
    _session_file_path(session_id)
    snapshot = get_snapshot(session_id, turn_index)
    if snapshot is None:
        raise HTTPException(404, "no snapshot for this session at that turn")

    project = get_project(snapshot.project_id)
    if project is None:
        raise HTTPException(404, "the project this snapshot belongs to no longer exists")

    try:
        path = validate_snapshot_relative_path(project, path)
        old, new = (
            commit_snapshot_file_content(snapshot, path)
            if view == "commit"
            else snapshot_file_content(project, snapshot, path)
        )
    except InvalidSnapshotPathError as e:
        raise HTTPException(400, str(e)) from e
    except RestoreError as e:
        raise HTTPException(500, f"could not read snapshot content: {e}") from e

    return SnapshotFileContentResponse(old=old, new=new)


class SnapshotRestoreRequest(BaseModel):
    turn_index: int
    # L'ancien contrat continue de restaurer l'etat avant le tour. La
    # nouvelle timeline demande explicitement "after" pour recharger le
    # commit selectionne.
    state: Literal["before", "after"] = "before"


@app.post("/sessions/{session_id}/snapshot/restore", tags=["Sessions"])
def restore_session_snapshot(session_id: str, body: SnapshotRestoreRequest) -> dict[str, bool]:
    """Undoes every write this session's tools made to its project folder
    from the given turn onward, bringing it back to the state
    ensure_snapshot captured just before that turn's first write - pass
    the oldest restore point (see GET .../snapshots) to undo the whole
    session, or a more recent one to only undo back to a specific turn.
    Destructive (see tools/snapshot.py's restore_snapshot) - the desktop
    app is expected to confirm with the user before calling this, the
    same way it does for any other irreversible action."""
    _session_file_path(session_id)
    snapshot = get_snapshot(session_id, body.turn_index)
    if snapshot is None:
        raise HTTPException(404, "no snapshot for this session at that turn")

    project = get_project(snapshot.project_id)
    if project is None:
        raise HTTPException(404, "the project this snapshot belongs to no longer exists")

    try:
        restore_snapshot(project, snapshot, body.state)
    except RestoreError as e:
        raise HTTPException(500, f"restore failed: {e}") from e

    return {"ok": True}


@app.get("/mcp/servers", tags=["MCP"])
def list_mcp_servers() -> list[mcp_client.ServerStatus]:
    return mcp_client.manager.status()


@app.post("/mcp/servers", tags=["MCP"])
def add_mcp_server(body: MCPServerCreate) -> list[mcp_client.ServerStatus]:
    config = mcp_client.MCPServerConfig(
        name=body.name, command=body.command, args=body.args, env=body.env, enabled=body.enabled
    )
    try:
        mcp_client.manager.add_server(config)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    return mcp_client.manager.status()


@app.put("/mcp/servers/{name}", tags=["MCP"])
def toggle_mcp_server(name: str, body: MCPServerToggle) -> list[mcp_client.ServerStatus]:
    try:
        mcp_client.manager.set_enabled(name, body.enabled)
    except KeyError as e:
        raise HTTPException(404, "MCP server not found") from e
    return mcp_client.manager.status()


@app.delete("/mcp/servers/{name}", tags=["MCP"])
def remove_mcp_server(name: str) -> list[mcp_client.ServerStatus]:
    mcp_client.manager.remove_server(name)
    return mcp_client.manager.status()


class ScheduledTaskCreate(BaseModel):
    prompt: str
    frequency: Literal["hourly", "daily", "weekly"]
    time_of_day: str = Field(pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    project_id: str
    # 0=Monday..6=Sunday - required for "weekly", ignored otherwise
    day_of_week: int | None = Field(default=None, ge=0, le=6)


class ScheduledTaskToggle(BaseModel):
    enabled: bool


@app.get("/scheduled_tasks", tags=["Scheduled Tasks"])
def list_scheduled_tasks() -> list[scheduled_tasks.ScheduledTask]:
    return scheduled_tasks.load_tasks()


@app.post("/scheduled_tasks", tags=["Scheduled Tasks"])
def create_scheduled_task(body: ScheduledTaskCreate) -> scheduled_tasks.ScheduledTask:
    project = get_project(body.project_id)
    if project is None:
        raise HTTPException(404, "project not found")
    if body.frequency == "weekly" and body.day_of_week is None:
        raise HTTPException(400, "day_of_week is required for a weekly task")
    if not body.prompt.strip():
        raise HTTPException(400, "prompt cannot be empty")

    # a dedicated session, created once here and reused for every future
    # occurrence (see storage/scheduled_tasks.py's own docstring) - its
    # history accumulates across runs the same way an ordinary
    # conversation's would.
    session_path = new_session_path()
    session_id = session_path.stem
    save_session(session_path, [build_system_message(session_id, project)])
    save_session_project(session_id, project.id)
    save_title(session_id, f"[Récurrent] {body.prompt.strip()[:60]}")

    return scheduled_tasks.create_task(
        prompt=body.prompt.strip(),
        frequency=body.frequency,
        time_of_day=body.time_of_day,
        project_id=body.project_id,
        session_id=session_id,
        day_of_week=body.day_of_week,
    )


@app.put("/scheduled_tasks/{task_id}", tags=["Scheduled Tasks"])
def toggle_scheduled_task(task_id: str, body: ScheduledTaskToggle) -> scheduled_tasks.ScheduledTask:
    task = scheduled_tasks.set_enabled(task_id, body.enabled)
    if task is None:
        raise HTTPException(404, "scheduled task not found")
    return task


@app.delete("/scheduled_tasks/{task_id}", tags=["Scheduled Tasks"])
def remove_scheduled_task(task_id: str) -> dict[str, bool]:
    """Only removes the schedule itself - its dedicated session (and
    whatever history it accumulated) is left alone, same as deleting a
    project only unlinks its conversations rather than erasing them."""
    if not scheduled_tasks.delete_task(task_id):
        raise HTTPException(404, "scheduled task not found")
    return {"ok": True}


@app.get("/projects", tags=["Projects"])
def list_projects() -> list[Project]:
    return load_projects()


@app.post("/projects", tags=["Projects"])
def add_project(body: ProjectCreate) -> list[Project]:
    folder = Path(body.folder_path)
    if not folder.is_dir():
        raise HTTPException(400, "folder not found")
    create_project(body.name, str(folder))
    return load_projects()


@app.put("/projects/{project_id}", tags=["Projects"])
def rename_project_endpoint(project_id: str, body: ProjectRename) -> list[Project]:
    if not rename_project(project_id, body.name):
        raise HTTPException(404, "project not found")
    return load_projects()


@app.delete("/projects/{project_id}", tags=["Projects"])
def remove_project(project_id: str) -> list[Project]:
    if get_project(project_id) is None:
        raise HTTPException(404, "project not found")
    # purge every snapshot this project has (across every session that
    # ever wrote to it) while the record - and its folder_path, needed to
    # clean up a git-backed snapshot's ref - can still be resolved (see
    # discard_snapshots_for_project's own docstring for why leaving these
    # behind means dead weight forever, not just an unused record)
    discard_snapshots_for_project(project_id)
    delete_project(project_id)
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
        # Never follow links while walking the project tree. `Path.is_dir()`
        # follows them, so a link to an external directory used to reveal
        # its names (and recurse through it) despite the project boundary.
        # Hiding every symlink is intentional: an internal directory link
        # can form a cycle too, and the file endpoint already validates the
        # resolved target before serving a requested file.
        if child.is_symlink():
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


@app.get("/projects/{project_id}/tree", tags=["Projects"])
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


@app.get("/projects/{project_id}/file", tags=["Projects"])
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
    if target.is_relative_to(ROOT_DIR):
        raise HTTPException(403, "path resolves inside the harness's own installation directory")
    if not target.is_relative_to(root):
        raise HTTPException(403, "path resolves outside the project folder")
    if not target.is_file():
        raise HTTPException(404, "file not found")

    return FileResponse(target)


@app.get("/subagents", tags=["Subagents"])
def list_subagents() -> list[subagents.SubagentTask]:
    return subagents.list_tasks()


class OrchestratorDispatch(BaseModel):
    task: str
    session_id: str | None = None
    project_id: str | None = None


@app.post("/orchestrator", tags=["Orchestrator"])
def dispatch_orchestrator(body: OrchestratorDispatch) -> dict[str, str]:
    """Entry point for the /multi-agents slash command: resolves/creates a
    session exactly like /chat does (same title generation, same project
    attachment for a new session), saves the task as a normal user
    message, then dispatches the multi-agent run against that session -
    once it finishes, its own exchange is appended there too (see
    orchestrator._append_result_to_session), so the conversation reads
    seamlessly afterward instead of needing a separate view."""
    budget = load_monthly_budget()
    if budget is not None and current_month_cost() > budget:
        raise HTTPException(
            402,
            f"monthly budget of ${budget:.2f} exceeded - raise or clear it in Settings "
            "(Logs & costs) to keep running multi-agent tasks",
        )

    session_path, messages, is_new = resolve_session(body.session_id, body.project_id)
    session_id = session_path.stem
    messages.append({"role": "user", "content": body.task})
    turn_index = turn_index_of(messages)

    if is_new:
        save_title(session_id, generate_conversation_title(body.task))

    save_session(session_path, messages)

    project_id = load_session_project(session_id)
    run_id = orchestrator.dispatch(
        body.task, project_id=project_id, session_id=session_id, turn_index=turn_index
    )
    return {"run_id": run_id, "session_id": session_id}


@app.get("/orchestrator/{run_id}", tags=["Orchestrator"])
def get_orchestrator_run(run_id: str) -> orchestrator.OrchestratorRun:
    run = orchestrator.get(run_id)
    if run is None:
        raise HTTPException(404, "orchestrator run not found")
    return run


@app.get("/background_tasks", tags=["Background Tasks"])
def list_background_tasks_endpoint(session_id: str | None = None) -> list[dict[str, object]]:
    return [background_tasks.summary(t) for t in background_tasks.list_tasks(session_id)]


@app.get("/background_tasks/{task_id}", tags=["Background Tasks"])
def get_background_task(task_id: str) -> dict[str, object]:
    task = background_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "background task not found")
    return background_tasks.detail(task)


@app.post("/background_tasks/{task_id}/stop", tags=["Background Tasks"])
def stop_background_task_endpoint(task_id: str) -> dict[str, object]:
    task = background_tasks.get(task_id)
    if task is None:
        raise HTTPException(404, "background task not found")
    background_tasks.stop(task_id)
    return background_tasks.detail(task)


@app.delete("/background_tasks/{task_id}", tags=["Background Tasks"])
def delete_background_task_endpoint(task_id: str) -> dict[str, bool]:
    if background_tasks.get(task_id) is None:
        raise HTTPException(404, "background task not found")
    result = background_tasks.delete(task_id)
    if result.startswith("error:"):
        raise HTTPException(409, result)
    return {"deleted": True}


@app.get("/logs", tags=["Logs"])
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


class ModelCostBreakdown(BaseModel):
    model: str
    calls: int
    total_tokens: int
    cost_usd: float


class ProjectCostBreakdown(BaseModel):
    project_id: str | None
    project_name: str
    calls: int
    total_tokens: int
    cost_usd: float


class DayCostBreakdown(BaseModel):
    date: str
    calls: int
    total_tokens: int
    cost_usd: float


class CostSummary(BaseModel):
    month: str
    total_calls: int
    total_tokens: int
    total_cost_usd: float
    by_model: list[ModelCostBreakdown]
    by_project: list[ProjectCostBreakdown]
    by_day: list[DayCostBreakdown]


class _CostBucket(TypedDict):
    calls: int
    total_tokens: int
    cost_usd: float


@app.get("/logs/cost_summary", tags=["Logs"])
def get_cost_summary() -> CostSummary:
    """Aggregated view of the current calendar month's spend across every
    conversation, subagent, and multi-agent run - by model, project, and
    day. GET /sessions/{id}/cost (the /cost command) stays scoped to
    one conversation; this is the "how much have I spent this month, and
    on what" view that was missing.

    Project is resolved from the event's own `project_id` when it has one
    (orchestrator/subagent calls log it directly - see agents/
    orchestrator.py, agents/subagents.py), otherwise from its
    `session_id` via load_session_project (older normal chat model_call
    events). An event with neither is bucketed under "Sans projet"; an
    explicit project id that no longer exists is shown as "Projet supprimé".
    Neither case is dropped, since both still represent real spend."""
    month = datetime.now().strftime("%Y-%m")
    events = events_for_month(month)

    by_model: dict[str, _CostBucket] = {}
    by_project: dict[str | None, _CostBucket] = {}
    by_day: dict[str, _CostBucket] = {}
    total_calls = 0
    total_tokens = 0
    total_cost = 0.0

    project_names = {p.id: p.name for p in load_projects()}

    for event in events:
        raw_model = event.get("model")
        raw_cost = event.get("cost_usd")
        # A model call with unknown pricing still belongs in the call/token
        # totals. Conversely, current_month_cost() intentionally counts any
        # future event carrying cost_usd even if it forgot a model field, so
        # keep this summary aligned with the budget source of truth by giving
        # that rare legacy/future case an explicit fallback bucket.
        if not isinstance(raw_model, str) and not isinstance(raw_cost, int | float):
            continue  # a tool_call, an error event, etc.
        model = raw_model if isinstance(raw_model, str) else "Modèle inconnu"
        cost = float(raw_cost) if isinstance(raw_cost, int | float) else 0.0

        raw_tokens = event.get("total_tokens")
        if isinstance(raw_tokens, int):
            tokens = raw_tokens
        else:
            prompt_tokens = event.get("prompt_tokens")
            completion_tokens = event.get("completion_tokens")
            tokens = (prompt_tokens if isinstance(prompt_tokens, int) else 0) + (
                completion_tokens if isinstance(completion_tokens, int) else 0
            )

        total_calls += 1
        total_tokens += tokens
        total_cost += cost

        model_bucket = by_model.setdefault(model, {"calls": 0, "total_tokens": 0, "cost_usd": 0.0})
        model_bucket["calls"] += 1
        model_bucket["total_tokens"] += tokens
        model_bucket["cost_usd"] += cost

        project_id = event.get("project_id")
        if not isinstance(project_id, str):
            session_id = event.get("session_id")
            project_id = load_session_project(session_id) if isinstance(session_id, str) else None

        project_bucket = by_project.setdefault(
            project_id, {"calls": 0, "total_tokens": 0, "cost_usd": 0.0}
        )
        project_bucket["calls"] += 1
        project_bucket["total_tokens"] += tokens
        project_bucket["cost_usd"] += cost

        timestamp = event.get("timestamp")
        day = timestamp[:10] if isinstance(timestamp, str) else "Date inconnue"
        day_bucket = by_day.setdefault(day, {"calls": 0, "total_tokens": 0, "cost_usd": 0.0})
        day_bucket["calls"] += 1
        day_bucket["total_tokens"] += tokens
        day_bucket["cost_usd"] += cost

    return CostSummary(
        month=month,
        total_calls=total_calls,
        total_tokens=total_tokens,
        total_cost_usd=round(total_cost, 6),
        by_model=[
            ModelCostBreakdown(
                model=model,
                calls=int(b["calls"]),
                total_tokens=int(b["total_tokens"]),
                cost_usd=round(b["cost_usd"], 6),
            )
            for model, b in sorted(by_model.items(), key=lambda kv: -kv[1]["cost_usd"])
        ],
        by_project=[
            ProjectCostBreakdown(
                project_id=project_id,
                project_name=(
                    "Sans projet"
                    if project_id is None
                    else project_names.get(project_id, "Projet supprimé")
                ),
                calls=int(b["calls"]),
                total_tokens=int(b["total_tokens"]),
                cost_usd=round(b["cost_usd"], 6),
            )
            for project_id, b in sorted(by_project.items(), key=lambda kv: -kv[1]["cost_usd"])
        ],
        by_day=[
            DayCostBreakdown(
                date=day,
                calls=int(b["calls"]),
                total_tokens=int(b["total_tokens"]),
                cost_usd=round(b["cost_usd"], 6),
            )
            for day, b in sorted(by_day.items())
        ],
    )


@app.get("/{asset_path:path}", include_in_schema=False)
def web_static_file(asset_path: str) -> FileResponse:
    if DEPLOYMENT_PROFILE is DeploymentProfile.WEB:
        target = WEB_FRONTEND_DIR / asset_path
        if target.is_relative_to(WEB_FRONTEND_DIR) and target.is_file():
            return FileResponse(target)
    raise HTTPException(404, "not found")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Run Triton's HTTP API")
    parser.add_argument(
        "--local-api-token-stdin",
        action="store_true",
        help="read the one-time local API token from stdin (used by the Tauri sidecar)",
    )
    args = parser.parse_args()
    if args.local_api_token_stdin:
        token = sys.stdin.readline().strip()
        if not token:
            parser.error("--local-api-token-stdin requires a non-empty token on stdin")
        LOCAL_API_TOKEN = token

    uvicorn.run(app, host="127.0.0.1", port=8000)
