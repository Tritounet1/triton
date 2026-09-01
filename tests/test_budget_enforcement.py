"""The monthly budget (settings.json's monthly_budget_usd) used to be
purely cosmetic - shown in Settings, checked nowhere else. These pin down
the two things that make it real: storage/logs.py's current_month_cost()
(the single source of truth server.py gates new calls on, and what GET
/settings/budget/status reports), and that /chat and /orchestrator both
refuse to start once it's exceeded, without ever reaching a real model
call."""

import json

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import logs, settings


def _write_log_line(logs_file, **fields) -> None:
    logs_file.parent.mkdir(parents=True, exist_ok=True)
    with logs_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    logs_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(logs, "LOGS_FILE", logs_file)
    monkeypatch.setattr(server, "LOGS_FILE", logs_file)

    settings_file = tmp_path / "settings.json"
    monkeypatch.setattr(settings, "SETTINGS_FILE", settings_file)


@pytest.fixture
def client():
    return TestClient(server.app)


# --- current_month_cost ---


def test_current_month_cost_is_zero_with_no_logs():
    assert logs.current_month_cost() == 0.0


def test_current_month_cost_sums_regardless_of_event_type():
    # log_event always stamps "now", exactly the case being tested - no
    # need to write raw lines by hand here like the other-months test does
    logs.log_event(type="model_call", cost_usd=0.01)
    logs.log_event(type="orchestrator_synthesis_call", cost_usd=0.02)
    logs.log_event(type="subagent_model_call", cost_usd=0.03)
    logs.log_event(type="tool_call")  # no cost_usd at all - must not crash, counts as 0

    assert logs.current_month_cost() == pytest.approx(0.06)


def test_current_month_cost_ignores_other_months(tmp_path):
    logs_file = tmp_path / "events.jsonl"
    _write_log_line(logs_file, type="model_call", timestamp="2020-01-15T10:00:00", cost_usd=99)
    logs.log_event(type="model_call", cost_usd=0.05)

    assert logs.current_month_cost() == pytest.approx(0.05)


# --- GET /settings/budget/status ---


def test_budget_status_with_no_budget_set(client):
    r = client.get("/settings/budget/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {"monthly_budget_usd": None, "spent_usd": 0.0, "exceeded": False}


def test_budget_status_reports_exceeded(client):
    settings.save_monthly_budget(1.0)
    logs.log_event(type="model_call", cost_usd=1.5)

    r = client.get("/settings/budget/status")
    body = r.json()
    assert body["monthly_budget_usd"] == 1.0
    assert body["spent_usd"] == pytest.approx(1.5)
    assert body["exceeded"] is True


def test_budget_status_not_exceeded_when_equal_to_budget(client):
    """Matches the pre-existing UI semantic (LogsSettings.tsx's
    budgetExceeded): strictly over, not at, the limit."""
    settings.save_monthly_budget(1.0)
    logs.log_event(type="model_call", cost_usd=1.0)

    r = client.get("/settings/budget/status")
    assert r.json()["exceeded"] is False


# --- /chat refuses to start once the budget is exceeded ---


def test_run_chat_stream_refuses_when_budget_exceeded(tmp_path, monkeypatch):
    # server.py does `from triton.llm.api import is_api_key_configured`, its
    # own separate name bound at import time - patching api.py's own name
    # wouldn't reach it (see test_sessions_pin.py for the same footgun with
    # SESSIONS_DIR). True here regardless: real .env key or not, this test
    # must reach the budget gate specifically, not stop earlier or later.
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    settings.save_monthly_budget(1.0)
    logs.log_event(type="model_call", cost_usd=2.0)

    session_path = tmp_path / "sessions" / "test.json"
    events = list(server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}]))

    # exactly "session" then "error" - never reaches the model-calling
    # part of the loop (which would need real network access and crash
    # this test if it were somehow reached)
    assert len(events) == 2
    assert "event: session" in events[0]
    assert "event: error" in events[1]
    assert "Budget mensuel" in events[1]


def test_run_chat_stream_proceeds_when_no_budget_set(tmp_path, monkeypatch):
    """Sanity check for the test above: without a budget, the generator
    must get past the budget gate - forced to stop at the "no API key"
    branch right before it instead (see the patch-target note above),
    rather than a real budget mischeck silently also blocking this case."""
    monkeypatch.setattr(server, "is_api_key_configured", lambda: False)

    session_path = tmp_path / "sessions" / "test.json"
    events = list(server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}]))

    assert len(events) == 2
    assert "Aucune clé API" in events[1]


# --- /orchestrator refuses to start once the budget is exceeded ---


def test_orchestrator_dispatch_refuses_when_budget_exceeded(client):
    settings.save_monthly_budget(1.0)
    logs.log_event(type="model_call", cost_usd=2.0)

    r = client.post("/orchestrator", json={"task": "do something"})
    assert r.status_code == 402
