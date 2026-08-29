"""Multi-agent orchestrator: a planner model breaks a task into role-tagged
subtasks, dispatches each one to a focused sub-agent running the model
configured for its role (model_roles.py) in a parallel background thread,
then synthesizes their results into one final answer.

Triggered from an ordinary conversation via the /multi-agents <task> slash
command (see server.py's /orchestrator endpoint) rather than a separate
page/mode: once a run finishes, its exchange is folded into that same
conversation's session file (sessions.py) so it reads like a normal
assistant turn from then on - each subtask becomes a fake tool call
(role name, model + description as its "arguments", result as the tool
response), which the desktop app's existing tool-call rendering already
knows how to display, live or from history, with no dedicated UI of its
own. Runs live only in memory (RUNS) for as long as they're in flight -
once folded into the session, the session file is the only copy that
matters, so there's nothing further to persist here.

Read-only for every role except one deliberate exception: a "code"
subtask gets write access (write_file/edit_file/delete_file/move_file,
plus run_tests) when - and only when - the run is scoped to a Project,
so those writes are always confined to that project's folder via the
same enforce_project_sandbox every conversation gets. With no project
selected, "code" stays exactly as read-only as every other role. This is
still unsupervised: nothing here goes through the confirmation flow a
live conversation has, so a code subtask can write/edit/delete files with
no human review in the loop - the project scope is the only safety net,
not a substitute for one. run_shell and git_commit are withheld from
every role regardless: arbitrary command execution and committing
autonomously are a different order of blast radius than file edits.
"""

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from api import call_chat
from logs import log_event
from main import to_tool_call_params
from model_roles import model_for_role
from pricing import estimate_cost
from projects import Project, get_project
from sessions import load_session, save_session, session_path
from subagents import SUBAGENT_TOOL_NAMES
from tools import enforce_project_sandbox

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

    from tools import Tool

SubtaskStatus = Literal["pending", "running", "done", "error"]
RunStatus = Literal["planning", "running", "done", "error"]

# raised from 6 after a real run hit this ceiling on two subtasks at once
# without concluding (a research search and a code read, neither an
# unusually hard task) - matches subagents.py's SUBAGENT_MAX_ITERATIONS=8,
# a little higher since a "code" subtask writing/testing files can
# reasonably need more back-and-forth than pure research.
MAX_SUBTASK_ITERATIONS = 10
MAX_SUBTASKS = 6

PLANNER_SYSTEM_PROMPT_TEMPLATE = (
    "You are a planning agent. Break the user's task into a small number of "
    "independent subtasks (as few as make sense, never more than "
    f"{MAX_SUBTASKS}), each tagged with the role best suited to it: "
    "'code' ({code_capability}), 'research' (web search, reading "
    "files/URLs, gathering information), 'vision' (analyzing an image or "
    "PDF already referenced in the task), or 'conversational' (anything "
    "else - drafting text, general reasoning). Respond with ONLY a JSON "
    'array, no prose, no markdown fences: [{{"role": "...", "description": '
    '"..."}}, ...]. Each description must be self-contained: the subtask '
    "has no access to this conversation, only what you write in its "
    "description."
)

CODE_ROLE_READ_ONLY = "reading/analyzing code, suggesting changes - it cannot write files"
CODE_ROLE_CAN_WRITE = (
    "reading, analyzing, and actually writing/editing/deleting files "
    "within the working directory given below - use it for changes you "
    "want actually made, not just described"
)


def _planner_system_prompt(can_write_code: bool) -> str:
    code_capability = CODE_ROLE_CAN_WRITE if can_write_code else CODE_ROLE_READ_ONLY
    return PLANNER_SYSTEM_PROMPT_TEMPLATE.format(code_capability=code_capability)


SUBTASK_SYSTEM_PROMPT_TEMPLATE = (
    "You are a focused sub-agent working on one part of a larger task, "
    "assigned by a planner. {capability_line} If web_search fails or "
    "returns nothing useful, don't compensate by guessing or fabricating "
    "URLs to fetch. Never infer or guess a date, version number, or other "
    "specific fact from context - quote it exactly as it appears in the "
    "source, and say plainly when a source doesn't state something "
    "explicitly instead of filling the gap with a guess. Answer concisely "
    "with what you did/found once you're done; this answer is the only "
    "part of your work the planner will see."
)

READ_ONLY_CAPABILITY_LINE = (
    "You cannot modify any files or run commands, only read, search, and browse the web."
)

CODE_WRITE_CAPABILITY_LINE = (
    "Your role is 'code': unlike other sub-agents, you can write, edit, "
    "and delete files within your working directory, and run the test "
    "suite - but you cannot run arbitrary shell commands or make a git "
    "commit. Nothing you do goes through a human confirmation step, so be "
    "conservative: make the smallest change that accomplishes the task, "
    "and run the tests after a change if the project has them."
)


def _subtask_system_prompt(can_write: bool) -> str:
    capability_line = CODE_WRITE_CAPABILITY_LINE if can_write else READ_ONLY_CAPABILITY_LINE
    return SUBTASK_SYSTEM_PROMPT_TEMPLATE.format(capability_line=capability_line)


# a "code" subtask gets these instead of SUBAGENT_TOOL_NAMES only when a
# project is scoped (see _run_subtask) - deliberately no run_shell
# (arbitrary command execution) and no git_commit (nothing should commit
# autonomously, unsupervised).
CODE_WRITE_TOOL_NAMES = SUBAGENT_TOOL_NAMES | {
    "write_file",
    "edit_file",
    "delete_file",
    "move_file",
    "run_tests",
}


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
    session_id: str | None = None


RUNS: dict[str, OrchestratorRun] = {}


def _append_result_to_session(run: OrchestratorRun) -> None:
    """Folds a finished run into its conversation's history. Each subtask
    becomes a fake tool call (its role as the "tool" name, model+task as
    its arguments, its result as the tool response) - the exact shape a
    real tool call/response pair has, so the desktop app's existing
    reconstruction of tool calls from session history renders it with no
    changes needed there, the same way it would for a real tool. The
    synthesis (or the error, if the run failed) is the final assistant
    message, same as any other reply."""
    assert run.session_id is not None
    path = session_path(run.session_id)
    try:
        messages = load_session(path)
    except (OSError, ValueError):
        return

    if run.subtasks:
        messages.append(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"multiagent_{s.id}",
                        "type": "function",
                        "function": {
                            "name": s.role,
                            "arguments": json.dumps({"model": s.model, "task": s.description}),
                        },
                    }
                    for s in run.subtasks
                ],
            }
        )
        for s in run.subtasks:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": f"multiagent_{s.id}",
                    "content": s.result or "(no result)",
                }
            )

    final_text = (
        run.final_result if run.status == "done" else (run.error or "multi-agent run failed")
    )
    messages.append(
        cast(
            "ChatCompletionMessageParam",
            {"role": "assistant", "content": final_text, "model": model_for_role("orchestrator")},
        )
    )
    save_session(path, messages)


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


def _run_subtask(subtask: Subtask, project: Project | None) -> None:
    from tools import TOOLS_REGISTRY

    can_write = subtask.role == "code" and project is not None
    tool_names = CODE_WRITE_TOOL_NAMES if can_write else SUBAGENT_TOOL_NAMES
    registry: dict[str, Tool] = {
        name: TOOLS_REGISTRY[name] for name in tool_names if name in TOOLS_REGISTRY
    }
    schema = [tool.schema for tool in registry.values()]

    project_line = f"\nWorking directory: {project.folder_path}\n" if project else ""
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _subtask_system_prompt(can_write)},
        {
            "role": "user",
            "content": f"Role: {subtask.role}{project_line}\nTask: {subtask.description}",
        },
    ]

    subtask.status = "running"
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
    except Exception as e:
        subtask.status = "error"
        subtask.result = f"{type(e).__name__}: {e}"


def _run(run: OrchestratorRun) -> None:
    project = get_project(run.project_id) if run.project_id else None
    project_context = f"\n\nWorking directory available: {project.folder_path}" if project else ""

    try:
        plan_reply = call_chat(
            [
                {"role": "system", "content": _planner_system_prompt(project is not None)},
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
        if run.session_id:
            _append_result_to_session(run)
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

    threads = [
        threading.Thread(target=_run_subtask, args=(s, project), daemon=True) for s in run.subtasks
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
    except Exception as e:
        run.status = "error"
        run.error = f"synthesis failed: {type(e).__name__}: {e}"

    if run.session_id:
        _append_result_to_session(run)


def dispatch(task: str, project_id: str | None = None, session_id: str | None = None) -> str:
    """Starts a multi-agent run in a background thread and returns its id
    immediately, without waiting for it to finish."""
    run = OrchestratorRun(
        id=uuid.uuid4().hex[:8], task=task, project_id=project_id, session_id=session_id
    )
    RUNS[run.id] = run
    threading.Thread(target=_run, args=(run,), daemon=True).start()
    return run.id


def get(run_id: str) -> OrchestratorRun | None:
    return RUNS.get(run_id)
