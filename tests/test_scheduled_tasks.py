"""Recurring prompts (PLAN.md's "Tâches récurrentes (façon cron)" entry):
storage/scheduled_tasks.py's compute_next_run/due_tasks/mark_fired (the
"no catch-up" contract), the CRUD endpoints, and that server.py's poll
loop actually resends a due task's prompt into its own dedicated session
with confirmations bypassed (force_yolo) since nobody is present to
answer one. No real thread/poll loop driven here: _run_scheduled_task is
called directly, same as other tests call run_chat_stream directly
instead of going through a real HTTP round-trip."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from openai.types.chat import (
    ChatCompletionMessageFunctionToolCall,
)
from openai.types.chat.chat_completion_message_function_tool_call import Function

import server
from triton.llm.api import ChatResult
from triton.storage import projects, scheduled_tasks, sessions, settings


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    # server.py does `from triton.storage import scheduled_tasks` (the
    # module itself, not individual names) - a single patch on the module
    # object is enough, unlike SESSIONS_DIR's own footgun elsewhere.
    monkeypatch.setattr(scheduled_tasks, "SCHEDULED_TASKS_FILE", tmp_path / "scheduled_tasks.json")


@pytest.fixture
def client():
    return TestClient(server.app)


def _project(tmp_path):
    folder = tmp_path / "myproject"
    folder.mkdir()
    return projects.create_project("test-project", str(folder))


# --- compute_next_run ---


def test_hourly_next_run_is_within_the_current_or_next_hour():
    # the hour part of time_of_day is always ignored for "hourly" - only
    # the minute matters (fires at that minute of every hour) - still
    # written as "HH:MM" for a uniform field format across frequencies
    now = datetime(2026, 1, 1, 10, 15, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("hourly", "00:45", None, now)
    assert next_run == datetime(2026, 1, 1, 10, 45, tzinfo=UTC)


def test_hourly_next_run_rolls_to_the_next_hour_if_the_minute_already_passed():
    now = datetime(2026, 1, 1, 10, 50, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("hourly", "00:45", None, now)
    assert next_run == datetime(2026, 1, 1, 11, 45, tzinfo=UTC)


def test_daily_next_run_is_later_today_if_the_time_hasnt_passed():
    now = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("daily", "20:00", None, now)
    assert next_run == datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


def test_daily_next_run_rolls_to_tomorrow_if_the_time_already_passed():
    now = datetime(2026, 1, 1, 21, 0, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("daily", "20:00", None, now)
    assert next_run == datetime(2026, 1, 2, 20, 0, tzinfo=UTC)


def test_weekly_next_run_lands_on_the_requested_weekday():
    # 2026-01-01 is a Thursday (weekday() == 3)
    now = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("weekly", "09:00", 0, now)  # next Monday
    assert next_run == datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    assert next_run.weekday() == 0


def test_weekly_next_run_rolls_a_full_week_if_today_but_time_passed():
    # 2026-01-01 is a Thursday (weekday() == 3)
    now = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    next_run = scheduled_tasks.compute_next_run("weekly", "09:00", 3, now)  # same weekday
    assert next_run == datetime(2026, 1, 8, 9, 0, tzinfo=UTC)


def test_weekly_requires_a_day_of_week():
    with pytest.raises(ValueError, match="day_of_week"):
        scheduled_tasks.compute_next_run("weekly", "09:00", None, datetime.now(UTC))


# --- due_tasks / mark_fired: the "no catch-up" contract ---


def test_due_tasks_finds_an_overdue_task():
    task = scheduled_tasks.create_task(
        prompt="check something",
        frequency="daily",
        time_of_day="09:00",
        project_id="p1",
        session_id="s1",
    )
    # force it into the past regardless of what create_task computed
    overdue = datetime.now(UTC) - timedelta(days=3)
    scheduled_tasks.mark_fired(task.id, overdue - timedelta(days=1))
    tasks = scheduled_tasks.load_tasks()
    tasks[0].next_run = overdue.isoformat()
    scheduled_tasks._save_all(tasks)

    due = scheduled_tasks.due_tasks(datetime.now(UTC))
    assert [t.id for t in due] == [task.id]


def test_mark_fired_recomputes_from_now_not_from_the_missed_occurrence():
    """The actual "no catch-up" behavior: a daily task overdue by 3 days
    gets a next_run computed from right now, once - never one that
    replays the 3 missed days one at a time."""
    task = scheduled_tasks.create_task(
        prompt="check something",
        frequency="daily",
        time_of_day="09:00",
        project_id="p1",
        session_id="s1",
    )
    tasks = scheduled_tasks.load_tasks()
    tasks[0].next_run = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    scheduled_tasks._save_all(tasks)

    fire_time = datetime.now(UTC)
    updated = scheduled_tasks.mark_fired(task.id, fire_time)

    assert updated is not None
    next_run = datetime.fromisoformat(updated.next_run)
    # squarely in the future relative to fire_time, not still in the past
    # and not several days away either (which a naive +=1 day per missed
    # occurrence loop would produce)
    assert next_run > fire_time
    assert next_run - fire_time < timedelta(days=1, hours=1)


def test_disabled_task_is_never_due():
    task = scheduled_tasks.create_task(
        prompt="check something",
        frequency="daily",
        time_of_day="09:00",
        project_id="p1",
        session_id="s1",
    )
    tasks = scheduled_tasks.load_tasks()
    tasks[0].next_run = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    scheduled_tasks._save_all(tasks)
    scheduled_tasks.set_enabled(task.id, False)

    assert scheduled_tasks.due_tasks(datetime.now(UTC)) == []


def test_delete_task_removes_it():
    task = scheduled_tasks.create_task(
        prompt="x", frequency="hourly", time_of_day="00:00", project_id="p1", session_id="s1"
    )
    assert scheduled_tasks.delete_task(task.id) is True
    assert scheduled_tasks.load_tasks() == []
    assert scheduled_tasks.delete_task(task.id) is False


# --- CRUD endpoints ---


def test_create_scheduled_task_creates_a_dedicated_session(tmp_path, client):
    project = _project(tmp_path)

    r = client.post(
        "/scheduled_tasks",
        json={
            "prompt": "résume les nouveaux fichiers",
            "frequency": "daily",
            "time_of_day": "09:00",
            "project_id": project.id,
        },
    )
    assert r.status_code == 200
    task = r.json()
    assert task["prompt"] == "résume les nouveaux fichiers"
    assert task["project_id"] == project.id

    session_id = task["session_id"]
    assert sessions.session_path(session_id).exists()
    assert sessions.load_session_project(session_id) == project.id
    assert sessions.load_title(session_id) == "[Récurrent] résume les nouveaux fichiers"


def test_create_scheduled_task_requires_day_of_week_for_weekly(tmp_path, client):
    project = _project(tmp_path)

    r = client.post(
        "/scheduled_tasks",
        json={
            "prompt": "x",
            "frequency": "weekly",
            "time_of_day": "09:00",
            "project_id": project.id,
        },
    )
    assert r.status_code == 400


def test_create_scheduled_task_404_for_unknown_project(client):
    r = client.post(
        "/scheduled_tasks",
        json={
            "prompt": "x",
            "frequency": "daily",
            "time_of_day": "09:00",
            "project_id": "does-not-exist",
        },
    )
    assert r.status_code == 404


def test_list_and_delete_scheduled_task(tmp_path, client):
    project = _project(tmp_path)
    r = client.post(
        "/scheduled_tasks",
        json={
            "prompt": "x",
            "frequency": "daily",
            "time_of_day": "09:00",
            "project_id": project.id,
        },
    )
    task_id = r.json()["id"]
    session_id = r.json()["session_id"]

    assert len(client.get("/scheduled_tasks").json()) == 1

    r = client.delete(f"/scheduled_tasks/{task_id}")
    assert r.status_code == 200
    assert client.get("/scheduled_tasks").json() == []
    # deleting the schedule doesn't delete its session/history
    assert sessions.session_path(session_id).exists()


def test_toggle_scheduled_task(tmp_path, client):
    project = _project(tmp_path)
    task_id = client.post(
        "/scheduled_tasks",
        json={
            "prompt": "x",
            "frequency": "daily",
            "time_of_day": "09:00",
            "project_id": project.id,
        },
    ).json()["id"]

    r = client.put(f"/scheduled_tasks/{task_id}", json={"enabled": False})
    assert r.status_code == 200
    assert r.json()["enabled"] is False


def test_toggle_and_delete_404_for_unknown_task(client):
    assert client.put("/scheduled_tasks/nope", json={"enabled": False}).status_code == 404
    assert client.delete("/scheduled_tasks/nope").status_code == 404


# --- firing a task: force_yolo bypasses confirmation ---


def _write_reply(project_dir):
    return ChatResult(
        content=None,
        tool_calls=[
            ChatCompletionMessageFunctionToolCall(
                id="call_1",
                type="function",
                function=Function(
                    name="write_file",
                    arguments=json.dumps({"path": str(project_dir / "hello.txt"), "content": "hi"}),
                ),
            )
        ],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="tool_calls",
    )


def test_run_scheduled_task_bypasses_confirmation_and_appends_the_prompt(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)
    project = _project(tmp_path)
    project_dir = tmp_path / "myproject"

    session_path = sessions.new_session_path()
    session_id = session_path.stem
    sessions.save_session(session_path, [])
    sessions.save_session_project(session_id, project.id)

    task = scheduled_tasks.create_task(
        prompt="fais un truc",
        frequency="daily",
        time_of_day="09:00",
        project_id=project.id,
        session_id=session_id,
    )

    call_count = 0

    def fake_timed_stream_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        # one tool call, then a final text reply - a stateless fake that
        # always returned the tool call would have run_chat_stream retry
        # it every iteration up to MAX_ITERATIONS, same as a real agentic
        # loop would for a model that never stops calling tools
        if call_count == 1:
            yield _write_reply(project_dir)
        else:
            yield ChatResult(
                content="done",
                tool_calls=[],
                model="test-model",
                prompt_tokens=1,
                completion_tokens=1,
                total_tokens=2,
                finish_reason="stop",
            )

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    server._run_scheduled_task(task)

    assert call_count == 2
    assert (project_dir / "hello.txt").read_text() == "hi"
    saved = sessions.load_session(session_path)
    assert any(m.get("role") == "user" and m.get("content") == "fais un truc" for m in saved)


def test_run_scheduled_task_skips_silently_if_its_session_was_deleted(tmp_path, monkeypatch):
    """The dedicated session can be deleted independently (DELETE
    /sessions/{id}) without deleting the schedule pointing at it - a
    later fire must not crash the whole poll loop over one broken task."""
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)

    def _fail_if_called(*_args, **_kwargs):
        raise AssertionError("must not attempt to call the model for a missing session")

    monkeypatch.setattr(server, "timed_stream_chat", _fail_if_called)

    task = scheduled_tasks.create_task(
        prompt="x",
        frequency="daily",
        time_of_day="09:00",
        project_id="p1",
        session_id="does-not-exist",
    )

    server._run_scheduled_task(task)  # must not raise
