import json

from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionMessageToolCallUnion,
    ChatCompletionMessageToolCallUnionParam,
)
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm

from api import call_chat
from sessions import latest_session_path, load_session, new_session_path, save_session
from tools import TOOLS, TOOLS_REGISTRY

SYSTEM_PROMPT = "You are a concise and clear assistant."
MAX_ITERATIONS = 10

# approximation grossiere : pas de vrai tokenizer, on estime a partir de la
# taille du json de l'historique (1 token ~= 4 caracteres, tres approximatif)
MAX_CONTEXT_CHARS = 8000
KEEP_RECENT_TURNS = 3


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
                f"[yellow]autoriser[/yellow] {name}({', '.join(f'{k}={v!r}' for k, v in args.items())}) ?",
                console=console,
                default=False,
            ):
                result = tool.fn(**args)
            else:
                result = "action refusée par l'utilisateur"

        args_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
        console.print(
            Panel(
                result,
                title=f"outil : {name}({args_repr})",
                title_align="left",
                border_style="yellow",
            )
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
    result = call_chat(summary_request)
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

            with console.status("[dim]réflexion...[/dim]", spinner="dots"):
                reply = call_chat(messages, tools=TOOLS)

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

            console.print(
                Panel(
                    Markdown(reply.content),
                    title="Triton",
                    title_align="left",
                    subtitle=f"[dim]{reply.model} · {reply.total_tokens} tokens ({reply.prompt_tokens} + {reply.completion_tokens})[/dim]",
                    subtitle_align="right",
                    border_style="magenta",
                )
            )
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
