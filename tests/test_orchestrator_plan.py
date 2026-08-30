"""_parse_plan turns the planner model's raw text into subtasks - a model
that ignores "respond with ONLY a JSON array" (wraps it in ```json fences,
omits a role, ...) shouldn't crash the whole run. _planner_system_prompt's
tests guard a real regression: its template contains literal '{"role": ...}'
JSON that a naive .format() call interprets as its own placeholders,
raising KeyError (see PLAN.md's changelog before it was fixed)."""

import json

import pytest

from triton.agents.orchestrator import (
    MAX_SUBTASKS,
    _parse_plan,
    _planner_system_prompt,
    _subtask_system_prompt,
)


def test_parses_a_clean_json_array():
    raw = '[{"role": "research", "description": "find the launch date"}]'
    assert _parse_plan(raw) == [{"role": "research", "description": "find the launch date"}]


def test_strips_markdown_code_fences():
    raw = '```json\n[{"role": "code", "description": "write the file"}]\n```'
    assert _parse_plan(raw) == [{"role": "code", "description": "write the file"}]


def test_missing_role_defaults_to_conversational():
    raw = '[{"description": "write a haiku"}]'
    assert _parse_plan(raw) == [{"role": "conversational", "description": "write a haiku"}]


def test_items_without_a_description_are_dropped():
    raw = '[{"role": "research", "description": "real one"}, {"role": "code"}]'
    assert _parse_plan(raw) == [{"role": "research", "description": "real one"}]


def test_non_list_json_raises():
    with pytest.raises(ValueError, match="not a JSON array"):
        _parse_plan('{"role": "research", "description": "oops, not wrapped in a list"}')


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        _parse_plan("not json at all")


def test_empty_plan_raises():
    with pytest.raises(ValueError, match="no usable subtasks"):
        _parse_plan("[]")


def test_plan_is_capped_at_max_subtasks():
    items = [{"role": "research", "description": f"task {i}"} for i in range(MAX_SUBTASKS + 5)]
    assert len(_parse_plan(json.dumps(items))) == MAX_SUBTASKS


@pytest.mark.parametrize("can_write_code", [True, False])
def test_planner_system_prompt_survives_format_with_literal_json_braces(can_write_code: bool):
    """Regression test: the template embeds a literal '[{"role": "...", ...}]'
    JSON example - .format() must not mistake those braces for its own
    placeholders and raise KeyError."""
    prompt = _planner_system_prompt(can_write_code)
    assert '[{"role": "...", "description": "..."}, ...]' in prompt


@pytest.mark.parametrize("can_write", [True, False])
def test_subtask_system_prompt_renders_without_error(can_write: bool):
    prompt = _subtask_system_prompt(can_write)
    assert "web_search" in prompt
