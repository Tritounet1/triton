"""Harness-wide settings (selected OpenRouter model, monthly budget...),
persisted to settings.json so choices survive restarts."""

import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


def _load() -> dict[str, object]:
    if not SETTINGS_FILE.exists():
        return {}
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(updates: dict[str, object]) -> None:
    # merges into the existing file rather than overwriting it, so setting
    # the budget doesn't wipe out the selected model and vice versa
    data = _load()
    data.update(updates)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def load_model() -> str:
    model = _load().get("model")
    return model if isinstance(model, str) and model else DEFAULT_MODEL


def save_model(model: str) -> None:
    _save({"model": model})


def load_monthly_budget() -> float | None:
    budget = _load().get("monthly_budget_usd")
    return budget if isinstance(budget, int | float) and budget > 0 else None


def save_monthly_budget(budget: float | None) -> None:
    _save({"monthly_budget_usd": budget})
