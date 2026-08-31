"""Two /model and /cost command backends:

- Per-session model override (storage/sessions.py's load_session_model/
  save_session_model, PUT+GET /sessions/{id}/model): mirrors pinning's
  marker-file pattern exactly, just with content instead of presence.
- Per-session cost (GET /sessions/{id}/cost): sums model_call log events
  tagged with a session_id (see chat_loop.py's timed_stream_chat), which
  only exists because of this feature - covered here at the endpoint
  level by writing fake log lines directly rather than a real model call.
"""

import json

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import sessions
from triton.storage.logs import LOGS_FILE as REAL_LOGS_FILE


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    # server.py imports SESSIONS_DIR/LOGS_FILE directly (`from ... import
    # X`), its own separate names bound at import time - patching the
    # storage module's constant alone leaves server.py's endpoints pointed
    # at the real files, so both need patching (see test_sessions_pin.py
    # for the same footgun).
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)

    logs_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(server, "LOGS_FILE", logs_file)


@pytest.fixture
def client():
    return TestClient(server.app)


def _new_session() -> str:
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    return path.stem


def _write_log_line(logs_file, **fields) -> None:
    logs_file.parent.mkdir(parents=True, exist_ok=True)
    with logs_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(fields) + "\n")


def test_new_session_has_no_model_override():
    session_id = _new_session()
    assert sessions.load_session_model(session_id) is None


def test_save_session_model_round_trips():
    session_id = _new_session()
    sessions.save_session_model(session_id, "openai/gpt-5")
    assert sessions.load_session_model(session_id) == "openai/gpt-5"


def test_delete_session_removes_the_model_override():
    session_id = _new_session()
    sessions.save_session_model(session_id, "openai/gpt-5")

    sessions.delete_session(session_id)

    assert not sessions.model_path(session_id).exists()


def test_model_endpoint_get_defaults_to_none(client):
    session_id = _new_session()
    r = client.get(f"/sessions/{session_id}/model")
    assert r.status_code == 200
    assert r.json() == {"model": None}


def test_model_endpoint_put_then_get(client):
    session_id = _new_session()

    r = client.put(f"/sessions/{session_id}/model", json={"model": "anthropic/claude-5"})
    assert r.status_code == 200
    assert r.json() == {"model": "anthropic/claude-5"}

    r = client.get(f"/sessions/{session_id}/model")
    assert r.json() == {"model": "anthropic/claude-5"}


def test_model_endpoint_put_404_for_unknown_session(client):
    r = client.put("/sessions/does-not-exist/model", json={"model": "x"})
    assert r.status_code == 404


def test_cost_endpoint_zero_when_no_logs_at_all(client):
    session_id = _new_session()
    r = client.get(f"/sessions/{session_id}/cost")
    assert r.status_code == 200
    assert r.json() == {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
    }


def test_cost_endpoint_sums_only_this_session_s_model_calls(client, tmp_path):
    # explicit, distinct ids rather than two back-to-back _new_session()
    # calls: new_session_path()'s id is second-granularity (see
    # storage/sessions.py), so two calls within the same second collide.
    session_id = "session-a"
    other_session_id = "session-b"
    sessions.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions.save_session(sessions.session_path(session_id), [])
    sessions.save_session(sessions.session_path(other_session_id), [])
    logs_file = tmp_path / "events.jsonl"

    _write_log_line(
        logs_file,
        type="model_call",
        session_id=session_id,
        model="m",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
    )
    _write_log_line(
        logs_file,
        type="model_call",
        session_id=session_id,
        model="m",
        prompt_tokens=200,
        completion_tokens=20,
        cost_usd=0.002,
    )
    # a different session's call - must not be counted
    _write_log_line(
        logs_file,
        type="model_call",
        session_id=other_session_id,
        model="m",
        prompt_tokens=9999,
        completion_tokens=9999,
        cost_usd=99,
    )
    # a tool_call event - not a model_call, must not be counted even
    # though it happens to share the same session_id
    _write_log_line(logs_file, type="tool_call", session_id=session_id, tool="read_file")
    # a model_call predating this feature, with no session_id at all -
    # must not crash and must not be attributed to any session
    _write_log_line(logs_file, type="model_call", model="m", prompt_tokens=1, completion_tokens=1)

    r = client.get(f"/sessions/{session_id}/cost")
    assert r.status_code == 200
    body = r.json()
    assert body["calls"] == 2
    assert body["prompt_tokens"] == 300
    assert body["completion_tokens"] == 70
    assert body["total_tokens"] == 370
    assert body["cost_usd"] == pytest.approx(0.003)


def test_real_logs_file_is_never_touched(client, tmp_path):
    """Fixture sanity check: writing through the cost endpoint's session
    (which itself writes nothing, but exercises the isolated LOGS_FILE)
    must never reach the real events.jsonl - the same class of mistake
    test_snapshot_endpoint.py's fixture caught earlier for projects.json."""
    real_size_before = REAL_LOGS_FILE.stat().st_size if REAL_LOGS_FILE.exists() else 0

    session_id = _new_session()
    _write_log_line(
        tmp_path / "events.jsonl",
        type="model_call",
        session_id=session_id,
        model="m",
        prompt_tokens=1,
        completion_tokens=1,
        cost_usd=0.0001,
    )
    client.get(f"/sessions/{session_id}/cost")

    real_size_after = REAL_LOGS_FILE.stat().st_size if REAL_LOGS_FILE.exists() else 0
    assert real_size_after == real_size_before
