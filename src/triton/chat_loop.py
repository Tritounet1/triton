"""Shared agentic-loop building blocks used by both entry points (main.py's
CLI and server.py's HTTP/SSE API) and by orchestrator.py's multi-agent
subtasks: building the system message, timing/logging model calls, and
compressing history once it grows too large. Kept independent of any
particular I/O model (no Rich, no FastAPI) so it can be reused as-is."""

import json
import time
from collections.abc import Iterator

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionMessageToolCallUnionParam,
    ChatCompletionToolParam,
)

from triton.api import ChatResult, call_chat, stream_chat
from triton.logs import log_event
from triton.pricing import estimate_cost
from triton.projects import Project
from triton.tools import load_memory

SYSTEM_PROMPT = "You are a concise and clear assistant."
# raised from 10: a single non-trivial task (e.g. building a multi-section
# styled page) can genuinely need this many tool calls, and the
# length-truncation retry in run_chat_stream now also spends an iteration
# each time it happens, both of which made 10 too tight in practice.
MAX_ITERATIONS = 25


def build_system_message(project: Project | None = None) -> ChatCompletionMessageParam:
    """Builds the initial system message for a new conversation, appending
    any facts saved via the remember tool so they don't need repeating, and
    scoping the conversation to a project's folder when it belongs to one."""
    content = SYSTEM_PROMPT
    if project is not None:
        content += (
            f"\n\nYou are working inside the project folder: {project.folder_path}\n"
            "Always use absolute paths starting with this folder for file operations "
            "(read_file, write_file, edit_file, grep, glob, delete_file, move_file, "
            "git_status, git_diff, git_commit, run_tests). This is enforced: a path "
            "outside this folder will be rejected, not just discouraged."
        )
    memory = load_memory()
    if memory:
        content += f"\n\nFacts remembered from previous conversations:\n{memory}"
    return {"role": "system", "content": content}


# rough approximation: no real tokenizer, estimated from the size of the
# history's json (1 token ~= 4 characters, very approximate)
MAX_CONTEXT_CHARS = 8000
KEEP_RECENT_TURNS = 3


def to_tool_call_params(
    tool_calls: list[ChatCompletionMessageToolCallUnion],
) -> list[ChatCompletionMessageToolCallUnionParam]:
    """Converts tool calls received from the API to the format expected as
    input, so they can be put back into the message history."""
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


def timed_call_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
) -> ChatResult:
    """Calls the model, timing the call and logging it."""
    start = time.perf_counter()
    reply = call_chat(messages, tools=tools)
    duration = time.perf_counter() - start

    log_event(
        type="model_call",
        model=reply.model,
        prompt_tokens=reply.prompt_tokens,
        completion_tokens=reply.completion_tokens,
        total_tokens=reply.total_tokens,
        tool_calls=len(reply.tool_calls),
        duration_seconds=round(duration, 3),
        cost_usd=estimate_cost(reply.model, reply.prompt_tokens, reply.completion_tokens),
    )
    return reply


def timed_stream_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
) -> Iterator[str | ChatResult]:
    """Streaming version of timed_call_chat: relays text chunks as they
    arrive, and logs the call once the final ChatResult is received."""
    start = time.perf_counter()
    for event in stream_chat(messages, tools=tools):
        if isinstance(event, str):
            yield event
            continue

        duration = time.perf_counter() - start
        log_event(
            type="model_call",
            model=event.model,
            prompt_tokens=event.prompt_tokens,
            completion_tokens=event.completion_tokens,
            total_tokens=event.total_tokens,
            tool_calls=len(event.tool_calls),
            duration_seconds=round(duration, 3),
            cost_usd=estimate_cost(event.model, event.prompt_tokens, event.completion_tokens),
        )
        yield event


def estimate_size(messages: list[ChatCompletionMessageParam]) -> int:
    return len(json.dumps(messages))


def turn_start_indices(messages: list[ChatCompletionMessageParam]) -> list[int]:
    """Indices of "user" messages in the history: each one marks the start of a turn."""
    return [i for i, m in enumerate(messages) if m["role"] == "user"]


def summarize(old_messages: list[ChatCompletionMessageParam]) -> str:
    transcript = json.dumps(old_messages, ensure_ascii=False, indent=2)
    summary_request: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "you summarize a conversation concisely, keeping the important facts, "
            "decisions, and tool results.",
        },
        {"role": "user", "content": f"summarize this conversation:\n\n{transcript}"},
    ]
    result = timed_call_chat(summary_request)
    return result.content or "(empty summary)"


def compress_history_if_needed(
    messages: list[ChatCompletionMessageParam],
) -> tuple[list[ChatCompletionMessageParam], str | None]:
    """Core compression logic, with no dependency on Rich (reused by the
    API). Summarizes the oldest turns if the history exceeds a threshold,
    keeping the system prompt and the most recent turns intact (so an
    assistant/tool_calls pair is never cut in the middle). Returns the
    history (unchanged or compressed) and a message to log, if compression
    happened."""
    if estimate_size(messages) <= MAX_CONTEXT_CHARS:
        return messages, None

    turns = turn_start_indices(messages)
    if len(turns) <= KEEP_RECENT_TURNS:
        return messages, None

    cutoff = turns[-KEEP_RECENT_TURNS]
    system_message = messages[0]
    old_messages = messages[1:cutoff]
    recent_messages = messages[cutoff:]

    summary = summarize(old_messages)

    compressed = [
        system_message,
        {"role": "system", "content": f"summary of the previous exchanges: {summary}"},
        *recent_messages,
    ]
    return compressed, f"history compressed: {len(old_messages)} messages summarized into 1"
