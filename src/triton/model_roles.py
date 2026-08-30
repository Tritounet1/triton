"""Which model handles which role in the multi-agent orchestrator
(orchestrator.py). ROLE_MODELS below is the built-in default for a role;
the Settings UI's per-role overrides (settings.json's "role_models", see
settings.py) take priority when set, so swapping a model for a role no
longer requires a code change. All OpenRouter ids for now (no
multi-provider abstraction yet, see issue #1 - deliberately skipped for
this first version).

Picks below favor a strong price/performance ratio for the role rather
than the single best model available - see PLAN.md's "Vrai multi-agent"
section for the reasoning and the OpenRouter pricing behind each pick.
"""

from triton.settings import load_role_model_overrides

Role = str  # "orchestrator" | "conversational" | "code" | "research" | "vision"

ROLE_MODELS: dict[str, str] = {
    "orchestrator": "anthropic/claude-sonnet-5",
    "conversational": "google/gemini-3.7-flash",
    "code": "deepseek/deepseek-v4-flash",
    "research": "deepseek/deepseek-v4-flash",
    "vision": "google/gemini-3.7-flash",
}

DEFAULT_ROLE = "research"


def model_for_role(role: str) -> str:
    default = ROLE_MODELS.get(role, ROLE_MODELS[DEFAULT_ROLE])
    return load_role_model_overrides().get(role, default)
