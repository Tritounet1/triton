import json
import time
from typing import cast

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.text import Text

from triton import mcp_client
from triton.llm.api import ChatResult
from triton.llm.chat_loop import (
    MAX_ITERATIONS,
    build_system_message,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
)
from triton.storage.logs import log_event
from triton.storage.sessions import (
    allow_always,
    latest_session_path,
    load_always_allowed,
    load_session,
    new_session_path,
    save_session,
)
from triton.tools import TOOLS, TOOLS_REGISTRY, invoke_tool

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
                result = invoke_tool(tool, name, args, session_id)
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
                    result = invoke_tool(tool, name, args, session_id)
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
        messages = [build_system_message(session_path.stem)]

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
                if reply.finish_reason == "length":
                    # see server.py's run_chat_stream for why this is
                    # recoverable rather than a hard failure
                    console.print(
                        "[dim]response cut off by the output length limit before producing "
                        "anything usable, asking the model to continue...[/dim]"
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
