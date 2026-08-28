import json
import time
from collections.abc import Iterator
from typing import cast

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionMessageToolCallUnionParam,
    ChatCompletionToolParam,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

import mcp_client
from api import ChatResult, call_chat, stream_chat
from logs import log_event
from pricing import estimate_cost
from projects import Project
from sessions import (
    allow_always,
    latest_session_path,
    load_always_allowed,
    load_session,
    new_session_path,
    save_session,
)
from tools import TOOLS, TOOLS_REGISTRY, load_memory

SYSTEM_PROMPT = "You are a concise and clear assistant."
MAX_ITERATIONS = 10


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


MAX_ARG_PREVIEW = 200


def format_args(args: dict[str, object]) -> str:
    """Renders a tool call's arguments for display, truncating any long
    string value (write_file's "content", run_shell's "command" with an
    embedded heredoc, edit_file's old_string/new_string...) to a short
    preview instead of dumping it in full."""
    parts: list[str] = []
    for k, v in args.items():
        if isinstance(v, str) and len(v) > MAX_ARG_PREVIEW:
            preview = v[:MAX_ARG_PREVIEW].replace("\n", " ")
            parts.append(f'{k}="{preview}..." ({len(v)} characters total)')
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def run_tool_calls(
    console: Console, session_id: str, tool_calls: list[ChatCompletionMessageToolCallUnion]
) -> list[ChatCompletionMessageParam]:
    """Runs each tool call requested by the model (asking for confirmation
    before tools that modify something), displays the result, and returns
    the corresponding "tool" messages to append to the history. The "always
    allow" choice (a) is only remembered for this conversation (session_id):
    a new conversation starts with a clean confirmation state."""
    tool_messages: list[ChatCompletionMessageParam] = []

    for tool_call in tool_calls:
        if tool_call.type != "function":
            continue

        name = tool_call.function.name
        raw_args = tool_call.function.arguments
        duration = 0.0

        try:
            args = json.loads(raw_args)
        except json.JSONDecodeError:
            result = f"error: invalid arguments ({raw_args})"
            args = {}
        else:
            tool = TOOLS_REGISTRY.get(name)

            if tool is None:
                result = f"unknown tool: {name}"
            elif tool.read_only or name in load_always_allowed(session_id):
                start = time.perf_counter()
                result = tool.fn(**args)
                duration = time.perf_counter() - start
            else:
                choice = Prompt.ask(
                    f"[yellow]allow[/yellow] {name}({format_args(args)})? "
                    "(y: once, a: always for this conversation, n: deny)",
                    console=console,
                    choices=["y", "n", "a"],
                    default="n",
                )
                if choice == "a":
                    allow_always(session_id, name)
                if choice in ("y", "a"):
                    start = time.perf_counter()
                    result = tool.fn(**args)
                    duration = time.perf_counter() - start
                else:
                    result = "action denied by the user"

        args_repr = format_args(args)
        console.print(
            Panel(
                result,
                title=f"tool: {name}({args_repr})",
                title_align="left",
                border_style="yellow",
            )
        )

        log_event(
            type="tool_call",
            tool=name,
            args=args,
            result_preview=result[:300],
            result_chars=len(result),
            duration_seconds=round(duration, 3),
        )

        tool_messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            }
        )

    return tool_messages


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


def compress_history(
    console: Console, messages: list[ChatCompletionMessageParam]
) -> list[ChatCompletionMessageParam]:
    """CLI wrapper: adds the spinner and Rich log around compress_history_if_needed."""
    with console.status("[dim]compressing history...[/dim]", spinner="dots"):
        compressed, log_message = compress_history_if_needed(messages)

    if log_message:
        console.print(f"[dim]{log_message}[/dim]\n")

    return compressed


def main():
    console = Console()
    session = PromptSession[str]()

    session_path = latest_session_path()
    messages: list[ChatCompletionMessageParam]
    if session_path:
        messages = load_session(session_path)
        console.print(f"[dim]session resumed: {session_path.name} ({len(messages)} messages)[/dim]")
    else:
        session_path = new_session_path()
        messages = [build_system_message()]

    console.rule("[bold cyan]Triton[/bold cyan]")

    mcp_configs = mcp_client.load_configs()
    if any(c.enabled for c in mcp_configs):
        with console.status("[dim]connecting to MCP servers...[/dim]", spinner="dots"):
            mcp_client.manager.connect_all_enabled()
        for status in mcp_client.manager.status():
            if not status["enabled"]:
                continue
            if status["connected"]:
                console.print(
                    f"[dim]MCP '{status['name']}' connected ({len(status['tools'])} tool(s))[/dim]"
                )
            else:
                console.print(f"[red]MCP '{status['name']}': {status['error']}[/red]")

    console.print("type 'exit' or 'quit' to quit\n", style="dim")

    while True:
        try:
            user_input = session.prompt(HTML("<ansigreen><b>You</b></ansigreen> › ")).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        messages.append({"role": "user", "content": user_input})
        messages = compress_history(console, messages)

        iteration = 0
        done = False

        while iteration < MAX_ITERATIONS and not done:
            iteration += 1

            content_parts: list[str] = []
            reply: ChatResult | None = None

            with Live(
                Text("thinking...", style="dim"), console=console, refresh_per_second=12
            ) as live:
                for event in timed_stream_chat(messages, tools=TOOLS):
                    if isinstance(event, str):
                        content_parts.append(event)
                        live.update(
                            Panel(
                                Markdown("".join(content_parts)),
                                title="Triton",
                                title_align="left",
                                border_style="magenta",
                            )
                        )
                    else:
                        reply = event

                if reply is not None and content_parts:
                    live.update(
                        Panel(
                            Markdown("".join(content_parts)),
                            title="Triton",
                            title_align="left",
                            subtitle=f"[dim]{reply.model} · {reply.total_tokens} tokens "
                            f"({reply.prompt_tokens} + {reply.completion_tokens})[/dim]",
                            subtitle_align="right",
                            border_style="magenta",
                        )
                    )
                elif not content_parts:
                    live.update(Text(""))

            assert reply is not None

            if reply.tool_calls:
                console.print(
                    f"[dim]iteration {iteration}: {len(reply.tool_calls)} tool call(s)[/dim]"
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": reply.content,
                        "tool_calls": to_tool_call_params(reply.tool_calls),
                    }
                )
                messages.extend(run_tool_calls(console, session_path.stem, reply.tool_calls))
                continue

            if reply.content is None:
                raise RuntimeError("the model returned neither text nor a tool call.")

            messages.append(
                cast(
                    ChatCompletionMessageParam,
                    {"role": "assistant", "content": reply.content, "model": reply.model},
                )
            )
            console.print()
            done = True

        if not done:
            console.print(
                f"[red]limit of {MAX_ITERATIONS} iterations reached, "
                "the model did not conclude.[/red]\n"
            )

        save_session(session_path, messages)

    save_session(session_path, messages)
    console.print("[dim]see you soon[/dim]")


if __name__ == "__main__":
    main()
