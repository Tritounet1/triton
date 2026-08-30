"""Harness-wide settings (selected OpenRouter model, monthly budget...),
persisted to settings.json so choices survive restarts."""

import json

from triton.paths import ROOT_DIR

SETTINGS_FILE = ROOT_DIR / "settings.json"
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


def load_openrouter_api_key() -> str | None:
    """The key entered through the Settings UI, if any - api.py falls back
    to the OPEN_ROUTER_API_KEY env var (.env) when this is unset, so the
    existing dev/CLI setup keeps working untouched."""
    key = _load().get("openrouter_api_key")
    return key if isinstance(key, str) and key.strip() else None


def save_openrouter_api_key(key: str | None) -> None:
    _save({"openrouter_api_key": key})


def load_role_model_overrides() -> dict[str, str]:
    """Per-role model overrides set through the Settings UI - model_roles.py's
    hardcoded ROLE_MODELS stays the fallback for any role without one."""
    overrides = _load().get("role_models")
    if not isinstance(overrides, dict):
        return {}
    return {
        role: model
        for role, model in overrides.items()
        if isinstance(role, str) and isinstance(model, str) and model
    }


def save_role_model_override(role: str, model: str | None) -> None:
    """`model=None` clears the override, falling back to ROLE_MODELS's
    default for that role again."""
    overrides = load_role_model_overrides()
    if model:
        overrides[role] = model
    else:
        overrides.pop(role, None)
    _save({"role_models": overrides})
