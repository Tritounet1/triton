import json

from openai.types.chat import ChatCompletionMessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from api import call_chat
from tools import TOOL_FUNCTIONS, TOOLS

SYSTEM_PROMPT = "You are a concise and clear assistant."


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

        with console.status("[dim]réflexion...[/dim]", spinner="dots"):
            reply = call_chat(messages, tools=TOOLS)

        if reply.tool_calls:
            # étape 4 : on exécute l'outil et on affiche le résultat une fois,
            # sans rappeler le modèle automatiquement (ça viendra à l'étape 5)
            for tool_call in reply.tool_calls:
                if tool_call.type != "function":
                    continue

                name = tool_call.function.name
                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    console.print(
                        f"[red]arguments invalides pour {name} : {tool_call.function.arguments}[/red]"
                    )
                    continue

                fn = TOOL_FUNCTIONS.get(name)
                result = fn(**args) if fn else f"outil inconnu : {name}"

                args_repr = ", ".join(f"{k}={v!r}" for k, v in args.items())
                console.print(
                    Panel(
                        result,
                        title=f"outil : {name}({args_repr})",
                        title_align="left",
                        border_style="yellow",
                    )
                )
            console.print()
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

    console.print("[dim]à bientôt[/dim]")


if __name__ == "__main__":
    main()
