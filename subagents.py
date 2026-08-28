"""Background sub-agents: a focused, read-only agentic loop dispatched by
the primary model to run independently in a background thread, so the main
conversation isn't blocked waiting for it. A first step toward multi-agent:
the sub-agent's own reasoning and tool calls stay isolated from the primary
conversation's context, only its final result comes back (fetched via the
check_subagent tool, or shown live in the desktop app's sidebar panel).

tools.py imports this module to register the dispatch_subagent/check_subagent
tools, so this module must not import tools.py at module load time (that
would be circular) - the one place it needs the tool registry (_run, to
build the sub-agent's restricted toolset) imports it locally instead,
deferred until the background thread actually runs.
"""

import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionMessageToolCallUnionParam,
)

from api import call_chat
from logs import log_event

if TYPE_CHECKING:
    from tools import Tool

SUBAGENT_MAX_ITERATIONS = 8

# read-only tools only: a sub-agent can research but never modify anything
# or touch shared mutable state (e.g. todo_write's global list)
SUBAGENT_TOOL_NAMES = {
    "read_file",
    "list_files",
    "grep",
    "glob",
    "fetch_url",
    "web_search",
    "git_status",
    "git_diff",
}

SUBAGENT_SYSTEM_PROMPT = (
    "You are a focused, read-only research sub-agent, dispatched by a "
    "primary assistant to investigate a specific question in the "
    "background. You cannot modify any files or run commands, only read, "
    "search, and browse the web. If web_search fails or returns nothing "
    "useful, don't compensate by guessing or fabricating URLs to fetch - "
    "most guesses 404 and waste your remaining turns. Report what you did "
    "find (even if partial) and note the limitation instead of endlessly "
    "retrying. Answer concisely with your findings once you're done; this "
    "answer is the only part of your work the primary assistant and the "
    "user will see."
)

# a check_subagent call on a still-running task less than this many seconds
# after the previous check gets told to stop polling instead of a plain
# "still running": without this, an impatient model calls check_subagent in
# a tight loop, burning its own iteration budget and cluttering the chat
# with near-identical "still waiting..." messages
MIN_CHECK_INTERVAL_SECONDS = 10.0
_last_checked: dict[str, float] = {}

TaskStatus = Literal["running", "done", "error"]


@dataclass
class SubagentTask:
    id: str
    task: str
    status: TaskStatus = "running"
    result: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


TASKS: dict[str, SubagentTask] = {}


def _to_tool_call_params(
    tool_calls: list[ChatCompletionMessageToolCallUnion],
) -> list[ChatCompletionMessageToolCallUnionParam]:
    params: list[ChatCompletionMessageToolCallUnionParam] = []
    for tool_call in tool_calls:
        if tool_call.type != "function":
            continue
        params.append(
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments,
                },
            }
        )
    return params


def _run(task_entry: SubagentTask) -> None:
    from tools import TOOLS_REGISTRY

    registry: dict[str, Tool] = {
        name: TOOLS_REGISTRY[name] for name in SUBAGENT_TOOL_NAMES if name in TOOLS_REGISTRY
    }
    schema = [tool.schema for tool in registry.values()]

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT},
        {"role": "user", "content": task_entry.task},
    ]

    try:
        for _ in range(SUBAGENT_MAX_ITERATIONS):
            reply = call_chat(messages, tools=schema)
            log_event(
                type="subagent_model_call",
                subagent_id=task_entry.id,
                model=reply.model,
                prompt_tokens=reply.prompt_tokens,
                completion_tokens=reply.completion_tokens,
                tool_calls=len(reply.tool_calls),
            )

            if not reply.tool_calls:
                task_entry.result = reply.content or "(the sub-agent returned no text)"
                task_entry.status = "done"
                return

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": _to_tool_call_params(reply.tool_calls),
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
                    args = {}
                else:
                    tool = registry.get(name)
                    result = tool.fn(**args) if tool else f"unknown tool: {name}"

                log_event(
                    type="subagent_tool_call",
                    subagent_id=task_entry.id,
                    tool=name,
                    args=args,
                    result_preview=result[:300],
                    result_chars=len(result),
                )
                messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": result})

        # ran out of iterations without a plain-text conclusion: force one
        # more call with no tools, so partial research (searches/fetches
        # that did succeed) gets synthesized into an answer instead of
        # silently discarded
        messages.append(
            {
                "role": "user",
                "content": "You're out of research turns. Answer now with your best "
                "understanding based on everything gathered above, noting any gaps "
                "or unconfirmed points.",
            }
        )
        final = call_chat(messages)
        task_entry.result = final.content or (
            f"(sub-agent stopped after {SUBAGENT_MAX_ITERATIONS} iterations without concluding)"
        )
        task_entry.status = "done"
    except Exception as e:
        task_entry.status = "error"
        task_entry.result = f"{type(e).__name__}: {e}"


def dispatch(task: str) -> str:
    """Starts a sub-agent in a background thread and returns immediately,
    without waiting for it to finish."""
    task_entry = SubagentTask(id=uuid.uuid4().hex[:8], task=task)
    TASKS[task_entry.id] = task_entry
    threading.Thread(target=_run, args=(task_entry,), daemon=True).start()
    return (
        f"Sub-agent dispatched (id={task_entry.id}), running in the background. "
        "Continue with other work; call check_subagent with this id later to "
        "see if it's done."
    )


def check(task_id: str) -> str:
    task_entry = TASKS.get(task_id)
    if task_entry is None:
        return f"error: no sub-agent with id {task_id}"

    if task_entry.status != "running":
        _last_checked.pop(task_id, None)
        return f"{task_entry.status}: {task_entry.result}"

    now = time.monotonic()
    last = _last_checked.get(task_id)
    _last_checked[task_id] = now
    if last is not None and now - last < MIN_CHECK_INTERVAL_SECONDS:
        return (
            "still running - you just checked this recently, there's nothing new "
            "to report yet. Stop polling now: tell the user it's still in progress "
            "and end your turn, or continue other work first. Check again in a "
            "later response instead of calling this again immediately."
        )
    return f"still running (dispatched {task_entry.created_at})"


def list_tasks() -> list[SubagentTask]:
    return sorted(TASKS.values(), key=lambda t: t.created_at, reverse=True)
