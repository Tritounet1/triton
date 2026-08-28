"""Harness-wide settings (currently just the selected OpenRouter model),
persisted to settings.json so the choice survives restarts."""

import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).parent / "settings.json"
DEFAULT_MODEL = "anthropic/claude-haiku-4.5"


def load_model() -> str:
    if not SETTINGS_FILE.exists():
        return DEFAULT_MODEL
    try:
        data = json.loads(SETTINGS_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return DEFAULT_MODEL
    model = data.get("model")
    return model if isinstance(model, str) and model else DEFAULT_MODEL


def save_model(model: str) -> None:
    SETTINGS_FILE.write_text(json.dumps({"model": model}, indent=2))
