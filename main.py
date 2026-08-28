import json
import time
from collections.abc import Iterator

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
from rich.prompt import Confirm
from rich.text import Text

from api import ChatResult, call_chat, stream_chat
from logs import log_event
from sessions import latest_session_path, load_session, new_session_path, save_session
from tools import TOOLS, TOOLS_REGISTRY

SYSTEM_PROMPT = "You are a concise and clear assistant."
MAX_ITERATIONS = 10

# approximation grossiere : pas de vrai tokenizer, on estime a partir de la
# taille du json de l'historique (1 token ~= 4 caracteres, tres approximatif)
MAX_CONTEXT_CHARS = 8000
KEEP_RECENT_TURNS = 3


def format_args(args: dict[str, object]) -> str:
    """Représente les arguments d'un appel d'outil pour l'affichage, sans
    jamais dumper un contenu potentiellement long (ex. le "content" de
    write_file), juste sa taille."""
    parts: list[str] = []
    for k, v in args.items():
        if k == "content" and isinstance(v, str):
            parts.append(f"{k}=<{len(v)} caractères>")
        else:
            parts.append(f"{k}={v!r}")
    return ", ".join(parts)


def run_tool_calls(
    console: Console, tool_calls: list[ChatCompletionMessageToolCallUnion]
) -> list[ChatCompletionMessageParam]:
    """Exécute chaque appel d'outil demandé par le modèle (en demandant une
    confirmation avant les outils qui modifient quelque chose), affiche le
    résultat, et renvoie les messages "tool" correspondants à ajouter à
    l'historique."""
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
            result = f"erreur : arguments invalides ({raw_args})"
            args = {}
        else:
            tool = TOOLS_REGISTRY.get(name)

            if tool is None:
                result = f"outil inconnu : {name}"
            elif tool.read_only or Confirm.ask(
                f"[yellow]autoriser[/yellow] {name}({format_args(args)}) ?",
                console=console,
                default=False,
            ):
                start = time.perf_counter()
                result = tool.fn(**args)
                duration = time.perf_counter() - start
            else:
                result = "action refusée par l'utilisateur"

        args_repr = format_args(args)
        console.print(
            Panel(
                result,
                title=f"outil : {name}({args_repr})",
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
    """Convertit les appels d'outils reçus de l'API vers le format attendu en entrée,
    pour pouvoir les remettre dans l'historique de messages."""
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
    """Appelle le modèle en chronométrant l'appel et en le loguant."""
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
    )
    return reply


def timed_stream_chat(
    messages: list[ChatCompletionMessageParam],
    tools: list[ChatCompletionToolParam] | None = None,
) -> Iterator[str | ChatResult]:
    """Version streaming de timed_call_chat : relaie les morceaux de texte au
    fur et à mesure, et logue l'appel une fois le ChatResult final reçu."""
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
        )
        yield event


def estimate_size(messages: list[ChatCompletionMessageParam]) -> int:
    return len(json.dumps(messages))


def turn_start_indices(messages: list[ChatCompletionMessageParam]) -> list[int]:
    """indices des messages "user" dans l'historique : chacun marque le début d'un tour."""
    return [i for i, m in enumerate(messages) if m["role"] == "user"]


def summarize(old_messages: list[ChatCompletionMessageParam]) -> str:
    transcript = json.dumps(old_messages, ensure_ascii=False, indent=2)
    summary_request: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "tu résumes une conversation de façon concise, en gardant les faits, "
            "décisions et résultats d'outils importants.",
        },
        {"role": "user", "content": f"résume cette conversation :\n\n{transcript}"},
    ]
    result = timed_call_chat(summary_request)
    return result.content or "(résumé vide)"


def compress_history(
    console: Console, messages: list[ChatCompletionMessageParam]
) -> list[ChatCompletionMessageParam]:
    """Résume les tours les plus anciens si l'historique dépasse un seuil, en
    gardant intacts le system prompt et les derniers tours (pour ne jamais
    couper un couple assistant/tool_calls en plein milieu)."""
    if estimate_size(messages) <= MAX_CONTEXT_CHARS:
        return messages

    turns = turn_start_indices(messages)
    if len(turns) <= KEEP_RECENT_TURNS:
        return messages

    cutoff = turns[-KEEP_RECENT_TURNS]
    system_message = messages[0]
    old_messages = messages[1:cutoff]
    recent_messages = messages[cutoff:]

    with console.status("[dim]compression de l'historique...[/dim]", spinner="dots"):
        summary = summarize(old_messages)

    console.print(
        f"[dim]historique compressé : {len(old_messages)} messages résumés en 1[/dim]\n"
    )

    return [
        system_message,
        {"role": "system", "content": f"résumé des échanges précédents : {summary}"},
        *recent_messages,
    ]


def main():
    console = Console()
    session = PromptSession[str]()

    session_path = latest_session_path()
    messages: list[ChatCompletionMessageParam]
    if session_path:
        messages = load_session(session_path)
        console.print(
            f"[dim]session reprise : {session_path.name} ({len(messages)} messages)[/dim]"
        )
    else:
        session_path = new_session_path()
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    console.rule("[bold cyan]Triton[/bold cyan]")
    console.print("tape 'exit' ou 'quit' pour quitter\n", style="dim")

    while True:
        try:
            user_input = session.prompt(HTML("<ansigreen><b>Toi</b></ansigreen> › ")).strip()
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
                Text("réflexion...", style="dim"), console=console, refresh_per_second=12
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
                    f"[dim]itération {iteration} : {len(reply.tool_calls)} appel(s) d'outil[/dim]"
                )
                messages.append(
                    {
                        "role": "assistant",
                        "content": reply.content,
                        "tool_calls": to_tool_call_params(reply.tool_calls),
                    }
                )
                messages.extend(run_tool_calls(console, reply.tool_calls))
                continue

            if reply.content is None:
                raise RuntimeError("le modèle n'a renvoyé ni texte ni appel d'outil.")

            messages.append({"role": "assistant", "content": reply.content})
            console.print()
            done = True

        if not done:
            console.print(
                f"[red]limite de {MAX_ITERATIONS} itérations atteinte, le modèle n'a pas conclu.[/red]\n"
            )

        save_session(session_path, messages)

    save_session(session_path, messages)
    console.print("[dim]à bientôt[/dim]")


if __name__ == "__main__":
    main()
