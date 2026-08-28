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
from tools import TOOLS, TOOLS_REGISTRY

SYSTEM_PROMPT = "You are a concise and clear assistant."
MAX_ITERATIONS = 10


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


def main():
    console = Console()
    session = PromptSession[str]()
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]

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

    console.print("[dim]à bientôt[/dim]")


if __name__ == "__main__":
    main()
