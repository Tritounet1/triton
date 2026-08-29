"""Which model handles which role in the multi-agent orchestrator
(orchestrator.py). This is the one place to touch to swap a model for a
role - nothing else in the codebase needs to change. All OpenRouter ids for
now (no multi-provider abstraction yet, see issue #1 - deliberately
skipped for this first version). A settings UI to edit this without a code
change is a natural next step, not built yet.

Picks below favor a strong price/performance ratio for the role rather
than the single best model available - see PLAN.md's "Vrai multi-agent"
section for the reasoning and the OpenRouter pricing behind each pick.
"""

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
    return ROLE_MODELS.get(role, ROLE_MODELS[DEFAULT_ROLE])
