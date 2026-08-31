"""Conversation pinning: a session is pinned purely by a `.pinned` marker
file's presence next to its `.json` (see storage/sessions.py's is_pinned/
set_pinned) - covers the storage layer directly and the PUT
/sessions/{id}/pin + GET /sessions endpoints on top."""

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import sessions


@pytest.fixture(autouse=True)
def _isolated_sessions_dir(tmp_path, monkeypatch):
    # server.py does `from triton.storage.sessions import SESSIONS_DIR`, its
    # own separate name bound at import time - patching sessions.SESSIONS_DIR
    # alone leaves server.py's endpoints (list_sessions, pin_session, ...)
    # pointed at the real sessions/ directory, so both need patching.
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)


@pytest.fixture
def client():
    return TestClient(server.app)


def _new_session() -> str:
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    return path.stem


def test_new_session_is_not_pinned():
    session_id = _new_session()
    assert sessions.is_pinned(session_id) is False


def test_set_pinned_toggles_the_marker_file():
    session_id = _new_session()
    sessions.set_pinned(session_id, True)
    assert sessions.is_pinned(session_id) is True

    sessions.set_pinned(session_id, False)
    assert sessions.is_pinned(session_id) is False


def test_delete_session_removes_the_pin(tmp_path):
    session_id = _new_session()
    sessions.set_pinned(session_id, True)

    sessions.delete_session(session_id)

    assert not sessions.pinned_path(session_id).exists()


def test_pin_endpoint_updates_and_persists(client):
    session_id = _new_session()

    r = client.put(f"/sessions/{session_id}/pin", json={"pinned": True})
    assert r.status_code == 200
    assert sessions.is_pinned(session_id) is True

    r = client.put(f"/sessions/{session_id}/pin", json={"pinned": False})
    assert r.status_code == 200
    assert sessions.is_pinned(session_id) is False


def test_pin_endpoint_404_for_unknown_session(client):
    r = client.put("/sessions/does-not-exist/pin", json={"pinned": True})
    assert r.status_code == 404


def test_list_sessions_reports_pinned_state(client):
    session_id = _new_session()
    sessions.set_pinned(session_id, True)

    r = client.get("/sessions")
    assert r.status_code == 200
    [entry] = r.json()
    assert entry["id"] == session_id
    assert entry["pinned"] is True
