"""Multi-agent orchestrator: a planner model breaks a task into role-tagged
subtasks, dispatches each one to a focused, read-only sub-agent running the
model configured for its role (model_roles.py) in a parallel background
thread, then synthesizes their results into one final answer.

Deliberately self-contained and separate from both subagents.py (a single
ad-hoc research sub-agent dispatched by the main conversation) and
server.py's session/project conversation loop: this is its own mode with
its own tracking, not merged into either. Per the "fusionner Projets et
multi-agent ?" decision in PLAN.md: Conversations and Runs stay two
separate things, but a run can optionally reference a project_id and
reuses the exact same Project entity and sandboxing (tools.py's
enforce_project_sandbox) that a conversation does - no second, duplicate
folder picker.

It reuses subagents.SUBAGENT_TOOL_NAMES for its subtasks' toolset (the
same safety boundary, not duplicated) and main.to_tool_call_params, but
everything else - planning, role routing, parallel dispatch, synthesis -
lives here.

Read-only, like subagents.py, for the same reason: nothing here goes
through the confirmation flow a live conversation has, so no subtask can
write files or run shell commands, even a "code" one - it can read and
analyze code, not change it. Lifting that needs a real confirmation story
for a background thread, which doesn't exist yet.

Runs are persisted to RUNS_DIR (one JSON file per run) and reloaded at
import time, so they survive a harness restart - unlike a live run's
threads, which don't: a run still "planning"/"running" when the harness
died is reloaded as "error" (no way to know how it would have finished).
"""

import json
import re
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from api import call_chat
from logs import log_event
from main import to_tool_call_params
from model_roles import model_for_role
from pricing import estimate_cost
from projects import Project, get_project
from subagents import SUBAGENT_TOOL_NAMES
from tools import enforce_project_sandbox

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

    from tools import Tool

SubtaskStatus = Literal["pending", "running", "done", "error"]
RunStatus = Literal["planning", "running", "done", "error"]

MAX_SUBTASK_ITERATIONS = 6
MAX_SUBTASKS = 6

RUNS_DIR = Path(__file__).parent / "orchestrator_runs"
_persist_lock = threading.Lock()

PLANNER_SYSTEM_PROMPT = (
    "You are a planning agent. Break the user's task into a small number of "
    "independent subtasks (as few as make sense, never more than "
    f"{MAX_SUBTASKS}), each tagged with the role best suited to it: "
    "'code' (reading/analyzing code, suggesting changes - it cannot write "
    "files), 'research' (web search, reading files/URLs, gathering "
    "information), 'vision' (analyzing an image or PDF already referenced "
    "in the task), or 'conversational' (anything else - drafting text, "
    "general reasoning). Respond with ONLY a JSON array, no prose, no "
    'markdown fences: [{"role": "...", "description": "..."}, ...]. Each '
    "description must be self-contained: the subtask has no access to this "
    "conversation, only what you write in its description."
)

SUBTASK_SYSTEM_PROMPT = (
    "You are a focused, read-only sub-agent working on one part of a "
    "larger task, assigned by a planner. You cannot modify any files or "
    "run commands, only read, search, and browse the web. If web_search "
    "fails or returns nothing useful, don't compensate by guessing or "
    "fabricating URLs to fetch. Never infer or guess a date, version "
    "number, or other specific fact from context - quote it exactly as it "
    "appears in the source, and say plainly when a source doesn't state "
    "something explicitly instead of filling the gap with a guess. Answer "
    "concisely with your findings once you're done; this answer is the "
    "only part of your work the planner will see."
)

SYNTHESIS_SYSTEM_PROMPT = (
    "You are the planner from earlier, reviewing the results of the "
    "subtasks you dispatched. Combine them into one coherent answer to "
    "the original task. Note any subtask that failed or came back "
    "incomplete instead of silently ignoring it."
)


@dataclass
class Subtask:
    id: str
    role: str
    description: str
    model: str
    status: SubtaskStatus = "pending"
    result: str | None = None


@dataclass
class OrchestratorRun:
    id: str
    task: str
    status: RunStatus = "planning"
    subtasks: list["Subtask"] = field(default_factory=list)
    final_result: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    project_id: str | None = None


def _persist(run: OrchestratorRun) -> None:
    RUNS_DIR.mkdir(exist_ok=True)
    with _persist_lock:
        (RUNS_DIR / f"{run.id}.json").write_text(json.dumps(asdict(run), indent=2))


def _load_persisted_runs() -> dict[str, OrchestratorRun]:
    if not RUNS_DIR.exists():
        return {}

    runs: dict[str, OrchestratorRun] = {}
    for path in RUNS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue

        subtasks = [Subtask(**s) for s in data.get("subtasks", [])]
        run = OrchestratorRun(
            id=data["id"],
            task=data["task"],
            status=data["status"],
            subtasks=subtasks,
            final_result=data.get("final_result"),
            error=data.get("error"),
            created_at=data["created_at"],
            project_id=data.get("project_id"),
        )
        if run.status in ("planning", "running"):
            # its background threads died with the harness - no way to
            # know how it would have finished
            run.status = "error"
            run.error = "the harness restarted before this run finished"
        runs[run.id] = run
    return runs


RUNS: dict[str, OrchestratorRun] = _load_persisted_runs()


def _parse_plan(raw: str) -> list[dict[str, str]]:
    # models often wrap JSON in ```json fences despite being told not to
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("plan is not a JSON array")

    subtasks: list[dict[str, str]] = []
    for item in data[:MAX_SUBTASKS]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip() or "conversational"
        description = str(item.get("description") or "").strip()
        if description:
            subtasks.append({"role": role, "description": description})

    if not subtasks:
        raise ValueError("plan contained no usable subtasks")
    return subtasks


def _run_subtask(run: OrchestratorRun, subtask: Subtask, project: Project | None) -> None:
    from tools import TOOLS_REGISTRY

    registry: dict[str, Tool] = {
        name: TOOLS_REGISTRY[name] for name in SUBAGENT_TOOL_NAMES if name in TOOLS_REGISTRY
    }
    schema = [tool.schema for tool in registry.values()]

    project_line = f"\nWorking directory: {project.folder_path}\n" if project else ""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SUBTASK_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": f"Role: {subtask.role}{project_line}\nTask: {subtask.description}",
        },
    ]

    subtask.status = "running"
    _persist(run)
    try:
        for _ in range(MAX_SUBTASK_ITERATIONS):
            reply = call_chat(messages, tools=schema, model=subtask.model)
            log_event(
                type="orchestrator_subtask_call",
                subtask_id=subtask.id,
                role=subtask.role,
                model=reply.model,
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                total_tokens=reply.total_tokens,
                tool_calls=len(reply.tool_calls),
                cost_usd=estimate_cost(reply.model, reply.prompt_tokens, reply.completion_tokens),
            )

            if not reply.tool_calls:
                if reply.content is None and reply.finish_reason == "length":
                    # see server.py's run_chat_stream for why this is
                    # recoverable rather than a hollow "no output" result
                    messages.append(
                        {
                            "role": "user",
                            "content": "Your last response was cut off by the output "
                            "length limit before it produced any content. Continue, "
                            "more concisely if needed.",
                        }
                    )
                    continue
                subtask.result = reply.content or "(the sub-agent returned no output)"
                subtask.status = "done"
                _persist(run)
                return

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
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = f"error: invalid arguments ({tool_call.function.arguments})"
                else:
                    sandbox_error = enforce_project_sandbox(name, args, project)
                    if sandbox_error is not None:
                        result = sandbox_error
                    else:
                        tool = registry.get(name)
                        if tool is None:
                            result = f"unknown tool: {name}"
                        else:
                            try:
                                result = tool.fn(**args)
                            except TypeError as e:
                                result = f"error: invalid arguments for {name} ({e})"
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

        subtask.result = f"(stopped after {MAX_SUBTASK_ITERATIONS} iterations without concluding)"
        subtask.status = "done"
        _persist(run)
    except Exception as e:
        subtask.status = "error"
        subtask.result = f"{type(e).__name__}: {e}"
        _persist(run)


def _run(run: OrchestratorRun) -> None:
    project = get_project(run.project_id) if run.project_id else None
    project_context = f"\n\nWorking directory available: {project.folder_path}" if project else ""

    try:
        plan_reply = call_chat(
            [
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": run.task + project_context},
            ],
            model=model_for_role("orchestrator"),
        )
        log_event(
            type="orchestrator_plan_call",
            run_id=run.id,
            model=plan_reply.model,
            prompt_tokens=plan_reply.prompt_tokens,
            completion_tokens=plan_reply.completion_tokens,
            total_tokens=plan_reply.total_tokens,
            cost_usd=estimate_cost(
                plan_reply.model, plan_reply.prompt_tokens, plan_reply.completion_tokens
            ),
        )
        if plan_reply.content is None:
            raise ValueError("planner returned no plan")
        raw_subtasks = _parse_plan(plan_reply.content)
    except Exception as e:
        run.status = "error"
        run.error = f"planning failed: {type(e).__name__}: {e}"
        _persist(run)
        return

    run.subtasks = [
        Subtask(
            id=uuid.uuid4().hex[:8],
            role=item["role"],
            description=item["description"],
            model=model_for_role(item["role"]),
        )
        for item in raw_subtasks
    ]
    run.status = "running"
    _persist(run)

    threads = [
        threading.Thread(target=_run_subtask, args=(run, s, project), daemon=True)
        for s in run.subtasks
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    subtask_report = "\n\n".join(f"[{s.role}] {s.description}\n-> {s.result}" for s in run.subtasks)
    try:
        synth_reply = call_chat(
            [
                {"role": "system", "content": SYNTHESIS_SYSTEM_PROMPT},
                {"role": "user", "content": run.task},
                {"role": "user", "content": f"Subtask results:\n\n{subtask_report}"},
            ],
            model=model_for_role("orchestrator"),
        )
        log_event(
            type="orchestrator_synthesis_call",
            run_id=run.id,
            model=synth_reply.model,
            prompt_tokens=synth_reply.prompt_tokens,
            completion_tokens=synth_reply.completion_tokens,
            total_tokens=synth_reply.total_tokens,
            cost_usd=estimate_cost(
                synth_reply.model, synth_reply.prompt_tokens, synth_reply.completion_tokens
            ),
        )
        run.final_result = synth_reply.content or "(the planner returned no synthesis)"
        run.status = "done"
        _persist(run)
    except Exception as e:
        run.status = "error"
        run.error = f"synthesis failed: {type(e).__name__}: {e}"
        _persist(run)


def dispatch(task: str, project_id: str | None = None) -> str:
    """Starts a multi-agent run in a background thread and returns its id
    immediately, without waiting for it to finish."""
    run = OrchestratorRun(id=uuid.uuid4().hex[:8], task=task, project_id=project_id)
    RUNS[run.id] = run
    _persist(run)
    threading.Thread(target=_run, args=(run,), daemon=True).start()
    return run.id


def get(run_id: str) -> OrchestratorRun | None:
    return RUNS.get(run_id)


def list_runs() -> list[OrchestratorRun]:
    return sorted(RUNS.values(), key=lambda r: r.created_at, reverse=True)
