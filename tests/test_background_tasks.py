"""background_tasks.start() enforces a hard cap on concurrently running
tasks (MAX_CONCURRENT_TASKS) - a real OS-process resource shared across
every conversation, previously unbounded. Real subprocess spawns here
(short sleep commands), same precedent as test_snapshot.py's real git
usage and test_run_code.py's real interpreter calls - every task started
during a test is explicitly stopped in teardown so nothing outlives it."""

import pytest

from triton import background_tasks as bg


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    state_dir = tmp_path / "background_tasks_state"
    monkeypatch.setattr(bg, "STATE_DIR", state_dir)
    monkeypatch.setattr(bg, "STATE_FILE", state_dir / "tasks.json")
    monkeypatch.setattr(bg, "TASKS", {})
    yield
    for task in list(bg.TASKS.values()):
        if task.status == "running":
            bg.stop(task.id)


def _start(session_id: str = "s1") -> str:
    return bg.start(session_id, "sleep 5", name="test")


def test_max_concurrent_tasks_default_is_five():
    assert bg.MAX_CONCURRENT_TASKS == 5


def test_running_count_only_counts_running_tasks():
    assert bg.running_count() == 0
    _start()
    assert bg.running_count() == 1


def test_start_is_rejected_once_the_cap_is_reached(monkeypatch):
    monkeypatch.setattr(bg, "MAX_CONCURRENT_TASKS", 2)
    _start()
    _start()
    assert bg.running_count() == 2

    result = _start()

    assert result == (
        "error: 2 background tasks are already running (across every conversation) - "
        "stop one with stop_background_task before starting another."
    )
    assert bg.running_count() == 2


def test_the_cap_applies_across_sessions_not_per_session(monkeypatch):
    monkeypatch.setattr(bg, "MAX_CONCURRENT_TASKS", 1)
    _start(session_id="session-a")

    result = _start(session_id="session-b")

    assert result.startswith("error:")
    assert bg.running_count() == 1


def test_start_succeeds_again_after_one_is_stopped(monkeypatch):
    monkeypatch.setattr(bg, "MAX_CONCURRENT_TASKS", 1)
    _start()
    [task_id] = list(bg.TASKS)
    assert bg.running_count() == 1

    assert _start().startswith("error:")

    bg.stop(task_id)
    assert bg.running_count() == 0

    result = _start()

    assert result.startswith("Background task started")
    assert bg.running_count() == 1


def test_start_is_reported_in_the_tool_schema_description():
    from triton.tools.background import REGISTRY

    description = REGISTRY["start_background_task"].schema["function"].get("description", "")
    assert f"At most {bg.MAX_CONCURRENT_TASKS} can run at once" in description
