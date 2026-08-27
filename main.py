from openai.types.chat import ChatCompletionMessageParam
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from api import call_chat

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
            reply = call_chat(messages)

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
