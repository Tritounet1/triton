import json
from collections import Counter

from rich.console import Console
from rich.table import Table

from logs import LOGS_FILE

PRICE_PER_MILLION_TOKENS: tuple[float, float] | None = None


def load_events() -> list[dict]:
    if not LOGS_FILE.exists():
        return []
    lines = LOGS_FILE.read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def main():
    console = Console()
    events = load_events()

    if not events:
        console.print(f"[dim]aucun log trouvé ({LOGS_FILE}).[/dim]")
        return

    model_calls = [e for e in events if e.get("type") == "model_call"]
    tool_calls = [e for e in events if e.get("type") == "tool_call"]

    total_prompt_tokens = sum(e.get("prompt_tokens", 0) for e in model_calls)
    total_completion_tokens = sum(e.get("completion_tokens", 0) for e in model_calls)
    total_tokens = total_prompt_tokens + total_completion_tokens
    tool_names = Counter(e.get("tool", "?") for e in tool_calls)

    table = Table(title="résumé des logs Triton")
    table.add_column("mesure")
    table.add_column("valeur", justify="right")

    table.add_row("appels au modèle", str(len(model_calls)))
    table.add_row("tokens (prompt)", str(total_prompt_tokens))
    table.add_row("tokens (completion)", str(total_completion_tokens))
    table.add_row("tokens (total)", str(total_tokens))
    table.add_row("appels d'outils", str(len(tool_calls)))
    table.add_row(
        "outil le plus utilisé",
        tool_names.most_common(1)[0][0] if tool_names else "-",
    )

    if PRICE_PER_MILLION_TOKENS is not None:
        price_in, price_out = PRICE_PER_MILLION_TOKENS
        cost = (total_prompt_tokens * price_in + total_completion_tokens * price_out) / 1_000_000
        table.add_row("coût estimé", f"${cost:.4f}")
    else:
        table.add_row("coût estimé", "(définis PRICE_PER_MILLION_TOKENS pour l'activer)")

    console.print(table)

    if tool_names:
        console.print("\n[bold]détail des outils :[/bold]")
        for name, count in tool_names.most_common():
            console.print(f"  {name} : {count}")


if __name__ == "__main__":
    main()
