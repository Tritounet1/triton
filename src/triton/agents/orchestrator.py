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
own. Runs live in memory (RUNS) while in flight, mirrored to disk
(storage/orchestrator_runs.py) so a harness restart doesn't lose one -
resume_incomplete_runs(), called once at startup, picks a crashed run
back up, keeping the results of any subtask that had already finished
and re-running the rest. Once a run reaches a terminal state and is
folded into its session, its persisted file is deleted - from then on
the session file is the only copy that matters.

A subtask can depend on another one in the same run via "depends_on"
(planner-assigned indices, translated to subtask ids once created) - see
_schedule_waves, which groups the run's subtasks into dependency-respecting
waves instead of firing every thread at once, so "research this, then
write code based on it" is possible within a single run while unrelated
subtasks still run in parallel as before.

Read-only for every role except one deliberate exception: a "code"
subtask gets write access (write_file/edit_file/delete_file/move_file,
plus run_tests) when - and only when - the run is scoped to a Project,
so those writes are always confined to that project's folder via the
same enforce_project_sandbox every conversation gets. With no project
selected, "code" stays exactly as read-only as every other role. This is
still unsupervised: nothing here goes through the confirmation flow a
live conversation has, so a code subtask can write/edit/delete files with
no human review in the loop - the project scope is the only safety net,
not a substitute for one. run_shell, run_code, and git_commit are
withheld from every role regardless: arbitrary command/code execution
and committing autonomously are a different order of blast radius than
file edits.
"""

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, cast

from triton.agents.subagents import SUBAGENT_TOOL_NAMES
from triton.llm.api import call_chat
from triton.llm.chat_loop import to_tool_call_params
from triton.llm.model_roles import model_for_role
from triton.llm.pricing import estimate_cost
from triton.storage.logs import log_event
from triton.storage.orchestrator_runs import delete_run, load_all_runs, save_run
from triton.storage.projects import Project, get_project
from triton.storage.sessions import load_session, save_session, session_path
from triton.tools import WRITE_TOOL_NAMES, enforce_project_sandbox, ensure_snapshot

if TYPE_CHECKING:
    from openai.types.chat import ChatCompletionMessageParam

    from triton.tools import Tool

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
    "subtasks (as few as make sense, never more than "
    f"{MAX_SUBTASKS}), each tagged with the role best suited to it: "
    "'code' ({code_capability}), 'research' (web search, reading "
    "files/URLs, gathering information), 'vision' (analyzing an image or "
    "PDF already referenced in the task), or 'conversational' (anything "
    "else - drafting text, general reasoning). Most subtasks should be "
    "independent so they can run in parallel, but when one genuinely needs "
    "another's result before it can start (e.g. code that implements what "
    'a research subtask finds), give it a "depends_on" array with the '
    "0-based indices of the subtasks it depends on - omit it or leave it "
    "empty otherwise. Respond with ONLY a JSON array, no prose, no "
    'markdown fences: [{{"role": "...", "description": "...", '
    '"depends_on": [...]}}, ...]. Each description must be self-contained: '
    "the subtask has no access to this conversation or to other subtasks' "
    "results, only what you write in its description (results of any "
    "subtasks it depends on are provided to it automatically, no need to "
    "repeat them here)."
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
class SubtaskToolCall:
    tool: str
    args: dict[str, object]
    result: str


@dataclass
class Subtask:
    id: str
    role: str
    description: str
    model: str
    # ids of other subtasks in the same run that must finish before this
    # one starts (see _schedule_waves) - empty for the common case of a
    # fully independent subtask, which behaves exactly as before.
    depends_on: list[str] = field(default_factory=list)
    status: SubtaskStatus = "pending"
    result: str | None = None
    # appended to live, as each tool call actually happens (see
    # _run_subtask) - GET /orchestrator/{run_id} exposes this directly, so
    # the desktop app can show what a subtask has done so far while it's
    # still running, not just its result once it's done.
    tool_calls: list["SubtaskToolCall"] = field(default_factory=list)


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


def _parse_plan(raw: str) -> list[dict[str, object]]:
    # models often wrap JSON in ```json fences despite being told not to
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("plan is not a JSON array")

    subtasks: list[dict[str, object]] = []
    for item in data[:MAX_SUBTASKS]:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip() or "conversational"
        description = str(item.get("description") or "").strip()
        if not description:
            continue
        raw_depends_on = item.get("depends_on")
        # ints only, bool excluded (bool is an int subclass in Python) -
        # a stray True/False in the array is a malformed plan, not a
        # 0/1 index
        depends_on = (
            [int(i) for i in raw_depends_on if isinstance(i, int) and not isinstance(i, bool)]
            if isinstance(raw_depends_on, list)
            else []
        )
        subtasks.append({"role": role, "description": description, "depends_on": depends_on})

    if not subtasks:
        raise ValueError("plan contained no usable subtasks")
    return subtasks


def _schedule_waves(subtasks: list[Subtask]) -> list[list[Subtask]]:
    """Groups subtasks into dependency-respecting waves (Kahn's algorithm):
    every subtask in a wave only depends on subtasks in earlier waves, so
    within one wave they can all run in parallel exactly like before -
    a plan with no depends_on at all produces a single wave, identical to
    the old fully-parallel behavior. A cycle in the plan (which the
    planner shouldn't produce, but nothing stops a bad one) can never
    resolve into a wave on its own, so whatever's left over when no
    further progress is possible is dumped into one final wave with its
    dependencies effectively ignored - better than deadlocking forever on
    subtasks that could never become ready."""
    by_id = {s.id: s for s in subtasks}
    remaining = {s.id: {d for d in s.depends_on if d in by_id} for s in subtasks}
    waves: list[list[Subtask]] = []
    done: set[str] = set()
    pending = set(by_id)
    while pending:
        ready = {sid for sid in pending if remaining[sid] <= done}
        if not ready:
            waves.append([by_id[sid] for sid in pending])
            break
        waves.append([by_id[sid] for sid in ready])
        done |= ready
        pending -= ready
    return waves


def _run_subtask(
    subtask: Subtask,
    project: Project | None,
    session_id: str | None,
    all_subtasks: list[Subtask],
) -> None:
    from triton.tools import TOOLS_REGISTRY

    can_write = subtask.role == "code" and project is not None
    tool_names = CODE_WRITE_TOOL_NAMES if can_write else SUBAGENT_TOOL_NAMES
    registry: dict[str, Tool] = {
        name: TOOLS_REGISTRY[name] for name in tool_names if name in TOOLS_REGISTRY
    }
    schema = [tool.schema for tool in registry.values()]

    project_line = f"\nWorking directory: {project.folder_path}\n" if project else ""
    deps_block = ""
    if subtask.depends_on:
        deps = [s for s in all_subtasks if s.id in subtask.depends_on]
        deps_report = "\n\n".join(f"[{d.role}] {d.description}\n-> {d.result}" for d in deps)
        deps_block = f"\n\nResults from the subtasks this one depends on:\n\n{deps_report}"
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": _subtask_system_prompt(can_write)},
        {
            "role": "user",
            "content": f"Role: {subtask.role}{project_line}\n"
            f"Task: {subtask.description}{deps_block}",
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
                args: dict[str, object] = {}
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
                            if name in WRITE_TOOL_NAMES and session_id is not None:
                                # this role runs fully unsupervised (see the
                                # module docstring) - the snapshot taken
                                # here is the only safety net a "code"
                                # subtask's writes get at all
                                ensure_snapshot(project, session_id)
                            try:
                                result = tool.fn(**args)
                            except TypeError as e:
                                result = f"error: invalid arguments for {name} ({e})"
                log_event(
                    type="orchestrator_subtask_tool_call",
                    subtask_id=subtask.id,
                    tool=name,
                    args=args,
                    result_preview=result[:300],
                    result_chars=len(result),
                )
                subtask.tool_calls.append(SubtaskToolCall(tool=name, args=args, result=result))
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

        # ran out of iterations without a plain-text conclusion: force one
        # more call with no tools, so partial work (searches/reads that did
        # succeed, a file already written) gets synthesized into an answer
        # instead of silently discarded - same recovery subagents.py already
        # has, missing here until a real research subtask hit exactly this
        # (10 tool-call iterations in a row, never once concluding).
        messages.append(
            {
                "role": "user",
                "content": "You're out of turns. Answer now with your best understanding "
                "based on everything gathered above, noting any gaps or unconfirmed points "
                "instead of continuing to search.",
            }
        )
        final = call_chat(messages, model=subtask.model)
        log_event(
            type="orchestrator_subtask_call",
            subtask_id=subtask.id,
            role=subtask.role,
            model=final.model,
            prompt_tokens=final.prompt_tokens,
            completion_tokens=final.completion_tokens,
            total_tokens=final.total_tokens,
            tool_calls=0,
            cost_usd=estimate_cost(final.model, final.prompt_tokens, final.completion_tokens),
        )
        subtask.result = final.content or (
            f"(stopped after {MAX_SUBTASK_ITERATIONS} iterations without concluding)"
        )
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
        _forget(run.id)
        return

    ids = [uuid.uuid4().hex[:8] for _ in raw_subtasks]
    run.subtasks = [
        Subtask(
            id=ids[i],
            role=cast(str, item["role"]),
            description=cast(str, item["description"]),
            model=model_for_role(cast(str, item["role"])),
            depends_on=[
                ids[d] for d in cast(list[int], item["depends_on"]) if d != i and 0 <= d < len(ids)
            ],
        )
        for i, item in enumerate(raw_subtasks)
    ]
    run.status = "running"
    _persist(run)

    _execute_subtasks(run, project)


def _execute_subtasks(run: OrchestratorRun, project: Project | None) -> None:
    """Runs every subtask that isn't already "done" (respecting dependency
    waves via _schedule_waves), then synthesizes the final answer. Reused
    both by a fresh run (every subtask starts "pending", so this is just
    "run everything") and by _resume_one picking a crashed run back up
    (subtasks already "done" before the restart are skipped, keeping their
    real results instead of redoing that work)."""
    for s in run.subtasks:
        if s.status != "done":
            s.status = "pending"
            s.result = None
            s.tool_calls = []

    for wave in _schedule_waves(run.subtasks):
        wave_to_run = [s for s in wave if s.status != "done"]
        if not wave_to_run:
            continue
        threads = [
            threading.Thread(
                target=_run_subtask,
                args=(s, project, run.session_id, run.subtasks),
                daemon=True,
            )
            for s in wave_to_run
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        _persist(run)

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
    _forget(run.id)


def _subtask_to_dict(s: Subtask) -> dict[str, object]:
    return {
        "id": s.id,
        "role": s.role,
        "description": s.description,
        "model": s.model,
        "depends_on": s.depends_on,
        "status": s.status,
        "result": s.result,
        "tool_calls": [
            {"tool": tc.tool, "args": tc.args, "result": tc.result} for tc in s.tool_calls
        ],
    }


def _subtask_from_dict(data: dict[str, object]) -> Subtask:
    return Subtask(
        id=cast(str, data["id"]),
        role=cast(str, data["role"]),
        description=cast(str, data["description"]),
        model=cast(str, data["model"]),
        depends_on=cast(list[str], data.get("depends_on") or []),
        status=cast(SubtaskStatus, data["status"]),
        result=cast("str | None", data.get("result")),
        tool_calls=[
            SubtaskToolCall(
                tool=cast(str, tc["tool"]),
                args=cast("dict[str, object]", tc["args"]),
                result=cast(str, tc["result"]),
            )
            for tc in cast("list[dict[str, object]]", data.get("tool_calls") or [])
        ],
    )


def _run_to_dict(run: OrchestratorRun) -> dict[str, object]:
    return {
        "id": run.id,
        "task": run.task,
        "status": run.status,
        "subtasks": [_subtask_to_dict(s) for s in run.subtasks],
        "final_result": run.final_result,
        "error": run.error,
        "created_at": run.created_at,
        "project_id": run.project_id,
        "session_id": run.session_id,
    }


def _run_from_dict(data: dict[str, object]) -> OrchestratorRun:
    return OrchestratorRun(
        id=cast(str, data["id"]),
        task=cast(str, data["task"]),
        status=cast(RunStatus, data["status"]),
        subtasks=[_subtask_from_dict(s) for s in cast("list[dict[str, object]]", data["subtasks"])],
        final_result=cast("str | None", data.get("final_result")),
        error=cast("str | None", data.get("error")),
        created_at=cast(str, data["created_at"]),
        project_id=cast("str | None", data.get("project_id")),
        session_id=cast("str | None", data.get("session_id")),
    )


def _persist(run: OrchestratorRun) -> None:
    save_run(run.id, _run_to_dict(run))


def _forget(run_id: str) -> None:
    delete_run(run_id)


def dispatch(task: str, project_id: str | None = None, session_id: str | None = None) -> str:
    """Starts a multi-agent run in a background thread and returns its id
    immediately, without waiting for it to finish."""
    run = OrchestratorRun(
        id=uuid.uuid4().hex[:8], task=task, project_id=project_id, session_id=session_id
    )
    RUNS[run.id] = run
    _persist(run)
    threading.Thread(target=_run, args=(run,), daemon=True).start()
    return run.id


def get(run_id: str) -> OrchestratorRun | None:
    return RUNS.get(run_id)


def _resume_one(run: OrchestratorRun) -> None:
    if not run.subtasks:
        # crashed before planning even finished producing subtasks -
        # nothing usable to resume, restart from scratch exactly like a
        # fresh dispatch would
        _run(run)
        return
    project = get_project(run.project_id) if run.project_id else None
    _execute_subtasks(run, project)


def resume_incomplete_runs() -> list[str]:
    """Called once at harness startup (see server.py's lifespan): reloads
    every run that was still "planning" or "running" when the process
    last stopped, and picks each one back up in a background thread -
    subtasks already "done" keep their results, everything else
    (including one that was "running" mid-thread when the process died,
    which gets no partial credit) is re-executed. A persisted file whose
    run had actually already reached a terminal state (a crash between
    that and _forget() removing the file) is just stale - dropped here
    rather than resumed. Returns the resumed run ids, for the startup
    log."""
    resumed: list[str] = []
    for data in load_all_runs():
        try:
            run = _run_from_dict(data)
        except (KeyError, TypeError, ValueError):
            continue
        if run.status not in ("planning", "running"):
            _forget(run.id)
            continue
        RUNS[run.id] = run
        resumed.append(run.id)
        threading.Thread(target=_resume_one, args=(run,), daemon=True).start()
    return resumed
