"""GET/PUT /settings/max_subtasks and /settings/multi_agent_roles
(+ POST .../reset) - what used to be orchestrator.py's hardcoded
MAX_SUBTASKS=6 and its fixed code/research/vision/conversational role set
are now both configurable through settings.json, defaulting to the same
values as before when never customized."""

import pytest
from fastapi.testclient import TestClient

import server
from triton.agents import orchestrator
from triton.storage import settings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")


@pytest.fixture
def client():
    return TestClient(server.app)


# --- max_subtasks ---


def test_max_subtasks_defaults_to_six(client):
    r = client.get("/settings/max_subtasks")
    assert r.status_code == 200
    assert r.json() == {"value": 6, "default": 6}


def test_max_subtasks_put_then_get(client):
    r = client.put("/settings/max_subtasks", json={"value": 3})
    assert r.status_code == 200
    assert r.json()["value"] == 3

    r = client.get("/settings/max_subtasks")
    assert r.json()["value"] == 3


def test_max_subtasks_null_clears_the_override(client):
    client.put("/settings/max_subtasks", json={"value": 3})
    r = client.put("/settings/max_subtasks", json={"value": None})
    assert r.json()["value"] == 6


def test_max_subtasks_rejects_a_value_below_one(client):
    r = client.put("/settings/max_subtasks", json={"value": 0})
    assert r.status_code == 400


# --- multi_agent_roles ---


def test_roles_default_to_the_built_in_set(client):
    r = client.get("/settings/multi_agent_roles")
    assert r.status_code == 200
    ids = [role["id"] for role in r.json()]
    assert ids == [role.id for role in orchestrator.DEFAULT_ROLES]


def test_roles_put_then_get(client):
    custom = [
        {
            "id": "translator",
            "label": "Translator",
            "description": "translates text between languages",
            "can_write": False,
            "system_prompt": "Always answer in French.",
        }
    ]
    r = client.put("/settings/multi_agent_roles", json={"roles": custom})
    assert r.status_code == 200
    assert r.json() == custom

    r = client.get("/settings/multi_agent_roles")
    assert r.json() == custom


def test_roles_reject_an_empty_list(client):
    r = client.put("/settings/multi_agent_roles", json={"roles": []})
    assert r.status_code == 400


def test_roles_reject_an_empty_id(client):
    r = client.put(
        "/settings/multi_agent_roles",
        json={"roles": [{"id": "", "label": "x", "description": "x"}]},
    )
    assert r.status_code == 400


def test_roles_reject_duplicate_ids(client):
    r = client.put(
        "/settings/multi_agent_roles",
        json={
            "roles": [
                {"id": "a", "label": "A", "description": "x"},
                {"id": "a", "label": "A again", "description": "y"},
            ]
        },
    )
    assert r.status_code == 400


def test_roles_reset_restores_the_defaults(client):
    client.put(
        "/settings/multi_agent_roles",
        json={"roles": [{"id": "translator", "label": "Translator", "description": "x"}]},
    )

    r = client.post("/settings/multi_agent_roles/reset")

    assert r.status_code == 200
    ids = [role["id"] for role in r.json()]
    assert ids == [role.id for role in orchestrator.DEFAULT_ROLES]


def test_orchestrator_load_roles_reflects_the_saved_setting(client):
    client.put(
        "/settings/multi_agent_roles",
        json={"roles": [{"id": "translator", "label": "Translator", "description": "x"}]},
    )

    roles = orchestrator.load_roles()

    assert [r.id for r in roles] == ["translator"]


def test_load_roles_falls_back_to_defaults_when_every_saved_entry_is_malformed():
    settings.save_multi_agent_roles([{"label": "no id, dropped"}, {"id": ""}, "not even a dict"])  # type: ignore[list-item]

    roles = orchestrator.load_roles()

    assert [r.id for r in roles] == [r.id for r in orchestrator.DEFAULT_ROLES]


def test_resolve_role_falls_back_to_a_synthetic_read_only_role_for_an_unknown_id():
    role = orchestrator._resolve_role("does-not-exist", orchestrator.DEFAULT_ROLES)

    assert role.id == "does-not-exist"
    assert role.can_write is False


def test_resolve_role_finds_a_matching_configured_role():
    role = orchestrator._resolve_role("code", orchestrator.DEFAULT_ROLES)

    assert role.can_write is True
