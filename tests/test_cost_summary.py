"""Global monthly cost dashboard aggregation.

The raw GET /logs endpoint is intentionally capped at 500 recent events, so
the dashboard summary must scan the complete current-month log instead. These
tests also pin project attribution for normal sessions, subagents/orchestrator
events, project-less calls, and projects deleted after a call was made.
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import logs, projects, sessions
from triton.storage.projects import Project


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    logs_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(logs, "LOGS_FILE", logs_file)
    monkeypatch.setattr(server, "LOGS_FILE", logs_file)
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(server, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


@pytest.fixture
def client():
    return TestClient(server.app)


def _write_log_line(**fields: object) -> None:
    logs.LOGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with logs.LOGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")


def test_cost_summary_is_empty_without_logs(client):
    response = client.get("/logs/cost_summary")

    assert response.status_code == 200
    assert response.json() == {
        "month": datetime.now().strftime("%Y-%m"),
        "total_calls": 0,
        "total_tokens": 0,
        "total_cost_usd": 0.0,
        "by_model": [],
        "by_project": [],
        "by_day": [],
    }


def test_cost_summary_aggregates_the_complete_month(client):
    project_one = Project(id="p1", name="Alpha", folder_path="/tmp/alpha")
    project_two = Project(id="p2", name="Beta", folder_path="/tmp/beta")
    projects.save_projects([project_one, project_two])
    sessions.save_session_project("session-alpha", project_one.id)

    logs.log_event(
        type="model_call",
        session_id="session-alpha",
        model="model-a",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        cost_usd=0.10,
    )
    # Older call shape without total_tokens: the endpoint falls back to the
    # prompt/completion sum rather than dropping its usage.
    logs.log_event(
        type="subagent_model_call",
        project_id=project_two.id,
        model="model-b",
        prompt_tokens=20,
        completion_tokens=30,
        cost_usd=0.20,
    )
    # Unknown pricing is still a real model call/token count, just $0 in the
    # monetary aggregate.
    logs.log_event(
        type="orchestrator_plan_call",
        project_id=project_two.id,
        model="model-b",
        total_tokens=25,
        cost_usd=None,
    )
    # Keep the summary aligned with current_month_cost() for a future/legacy
    # cost event that carries no model id.
    logs.log_event(
        type="future_cost_event",
        project_id=project_two.id,
        total_tokens=0,
        cost_usd=0.05,
    )
    logs.log_event(
        type="model_call",
        model="model-a",
        total_tokens=10,
        cost_usd=0.01,
    )
    logs.log_event(
        type="model_call",
        project_id="deleted-project",
        model="model-c",
        total_tokens=5,
        cost_usd=0.02,
    )
    logs.log_event(type="tool_call", tool="read_file")
    _write_log_line(
        type="model_call",
        timestamp="2020-01-15T10:00:00",
        model="old-model",
        total_tokens=999,
        cost_usd=99,
    )

    response = client.get("/logs/cost_summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 6
    assert body["total_tokens"] == 240
    assert body["total_cost_usd"] == pytest.approx(0.38)
    assert body["total_cost_usd"] == pytest.approx(logs.current_month_cost())

    assert body["by_model"] == [
        {"model": "model-b", "calls": 2, "total_tokens": 75, "cost_usd": 0.2},
        {"model": "model-a", "calls": 2, "total_tokens": 160, "cost_usd": 0.11},
        {"model": "Modèle inconnu", "calls": 1, "total_tokens": 0, "cost_usd": 0.05},
        {"model": "model-c", "calls": 1, "total_tokens": 5, "cost_usd": 0.02},
    ]
    assert body["by_project"] == [
        {
            "project_id": "p2",
            "project_name": "Beta",
            "calls": 3,
            "total_tokens": 75,
            "cost_usd": 0.25,
        },
        {
            "project_id": "p1",
            "project_name": "Alpha",
            "calls": 1,
            "total_tokens": 150,
            "cost_usd": 0.1,
        },
        {
            "project_id": "deleted-project",
            "project_name": "Projet supprimé",
            "calls": 1,
            "total_tokens": 5,
            "cost_usd": 0.02,
        },
        {
            "project_id": None,
            "project_name": "Sans projet",
            "calls": 1,
            "total_tokens": 10,
            "cost_usd": 0.01,
        },
    ]
    assert body["by_day"] == [
        {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "calls": 6,
            "total_tokens": 240,
            "cost_usd": pytest.approx(0.38),
        }
    ]
