"""_parse_plan turns the planner model's raw text into subtasks - a model
that ignores "respond with ONLY a JSON array" (wraps it in ```json fences,
omits a role, ...) shouldn't crash the whole run. _planner_system_prompt's
tests guard a real regression: its template contains literal '{"role": ...}'
JSON that a naive .format() call interprets as its own placeholders,
raising KeyError (see PLAN.md's changelog before it was fixed)."""

import json

import pytest

from triton.agents.orchestrator import (
    DEFAULT_ROLES,
    MultiAgentRole,
    _parse_plan,
    _planner_system_prompt,
    _subtask_system_prompt,
)

MAX_SUBTASKS = 6


def test_parses_a_clean_json_array():
    raw = '[{"role": "research", "description": "find the launch date"}]'
    assert _parse_plan(raw, MAX_SUBTASKS) == [
        {"role": "research", "description": "find the launch date", "depends_on": []}
    ]


def test_strips_markdown_code_fences():
    raw = '```json\n[{"role": "code", "description": "write the file"}]\n```'
    assert _parse_plan(raw, MAX_SUBTASKS) == [
        {"role": "code", "description": "write the file", "depends_on": []}
    ]


def test_missing_role_defaults_to_conversational():
    raw = '[{"description": "write a haiku"}]'
    assert _parse_plan(raw, MAX_SUBTASKS) == [
        {"role": "conversational", "description": "write a haiku", "depends_on": []}
    ]


def test_items_without_a_description_are_dropped():
    raw = '[{"role": "research", "description": "real one"}, {"role": "code"}]'
    assert _parse_plan(raw, MAX_SUBTASKS) == [
        {"role": "research", "description": "real one", "depends_on": []}
    ]


def test_parses_depends_on_indices():
    raw = (
        '[{"role": "research", "description": "find prices"}, '
        '{"role": "code", "description": "write a script using them", "depends_on": [0]}]'
    )
    plan = _parse_plan(raw, MAX_SUBTASKS)
    assert plan[0]["depends_on"] == []
    assert plan[1]["depends_on"] == [0]


def test_non_list_or_non_int_depends_on_entries_are_ignored():
    raw = (
        '[{"role": "research", "description": "a"}, '
        '{"role": "code", "description": "b", "depends_on": [0, "oops", true, 1.5, null]}]'
    )
    plan = _parse_plan(raw, MAX_SUBTASKS)
    assert plan[1]["depends_on"] == [0]


def test_depends_on_defaults_to_empty_when_absent_or_wrong_type():
    raw = '[{"role": "research", "description": "a", "depends_on": "not a list"}]'
    assert _parse_plan(raw, MAX_SUBTASKS)[0]["depends_on"] == []


def test_non_list_json_raises():
    with pytest.raises(ValueError, match="not a JSON array"):
        _parse_plan(
            '{"role": "research", "description": "oops, not wrapped in a list"}', MAX_SUBTASKS
        )


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        _parse_plan("not json at all", MAX_SUBTASKS)


def test_empty_plan_raises():
    with pytest.raises(ValueError, match="no usable subtasks"):
        _parse_plan("[]", MAX_SUBTASKS)


def test_plan_is_capped_at_max_subtasks():
    items = [{"role": "research", "description": f"task {i}"} for i in range(MAX_SUBTASKS + 5)]
    assert len(_parse_plan(json.dumps(items), MAX_SUBTASKS)) == MAX_SUBTASKS


def test_plan_cap_follows_the_configured_value_not_a_hardcoded_one():
    items = [{"role": "research", "description": f"task {i}"} for i in range(10)]
    assert len(_parse_plan(json.dumps(items), 3)) == 3


@pytest.mark.parametrize("project_scoped", [True, False])
def test_planner_system_prompt_survives_format_with_literal_json_braces(project_scoped: bool):
    """Regression test: the template embeds a literal '[{"role": "...", ...}]'
    JSON example - .format() must not mistake those braces for its own
    placeholders and raise KeyError."""
    prompt = _planner_system_prompt(DEFAULT_ROLES, MAX_SUBTASKS, project_scoped)
    assert '[{"role": "...", "description": "...", "depends_on": [...]}, ...]' in prompt


def test_planner_system_prompt_lists_every_configured_role():
    prompt = _planner_system_prompt(DEFAULT_ROLES, MAX_SUBTASKS, project_scoped=True)
    for role in DEFAULT_ROLES:
        assert f"'{role.id}'" in prompt


def test_planner_system_prompt_notes_write_roles_are_read_only_without_a_project():
    prompt = _planner_system_prompt(DEFAULT_ROLES, MAX_SUBTASKS, project_scoped=False)
    assert "read-only for now" in prompt


def test_planner_system_prompt_reflects_the_configured_max_subtasks():
    prompt = _planner_system_prompt(DEFAULT_ROLES, 3, project_scoped=True)
    assert "never more than 3" in prompt


def test_planner_system_prompt_reflects_a_custom_role_set():
    custom = [MultiAgentRole(id="translator", label="translator", description="translates text")]
    prompt = _planner_system_prompt(custom, MAX_SUBTASKS, project_scoped=True)
    assert "'translator'" in prompt
    assert "'code'" not in prompt


@pytest.mark.parametrize("can_write", [True, False])
def test_subtask_system_prompt_renders_without_error(can_write: bool):
    role = DEFAULT_ROLES[0]
    prompt = _subtask_system_prompt(role, can_write)
    assert "web_search" in prompt


def test_subtask_system_prompt_appends_the_roles_custom_system_prompt():
    role = MultiAgentRole(
        id="translator",
        label="translator",
        description="translates text",
        system_prompt="Always answer in French.",
    )
    prompt = _subtask_system_prompt(role, can_write=False)
    assert "Always answer in French." in prompt
