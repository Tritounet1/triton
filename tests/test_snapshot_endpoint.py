"""GET /sessions/{id}/snapshot and POST /sessions/{id}/snapshot/restore -
the desktop app's "undo this session's writes" affordance (see
triton/tools/snapshot.py for the actual git/copy logic, already covered
directly in test_snapshot.py). These tests exercise the HTTP layer on top:
404s when there's nothing to restore, and that a restore actually reaches
the project folder end to end."""

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import projects, sessions, snapshots
from triton.tools import snapshot as snap


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(snapshots, "SNAPSHOTS_FILE", tmp_path / "snapshots.json")
    monkeypatch.setattr(snap, "BACKUP_ROOT", tmp_path / "snapshot_backups")
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")


@pytest.fixture
def client():
    return TestClient(server.app)


def _project(tmp_path):
    folder = tmp_path / "myproject"
    folder.mkdir()
    return projects.create_project("test-project", str(folder))


def test_get_snapshot_404_when_none_exists(client):
    r = client.get("/sessions/no-such-session/snapshot")
    assert r.status_code == 404


def test_get_snapshot_returns_kind_and_created_at(tmp_path, client):
    project = _project(tmp_path)
    snap.ensure_snapshot(project, "session1")

    r = client.get("/sessions/session1/snapshot")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "copy"
    assert body["created_at"]


def test_restore_404_when_no_snapshot(client):
    r = client.post("/sessions/no-such-session/snapshot/restore")
    assert r.status_code == 404


def test_restore_404_when_project_was_deleted(tmp_path, client):
    project = _project(tmp_path)
    snap.ensure_snapshot(project, "session1")
    projects.delete_project(project.id)

    r = client.post("/sessions/session1/snapshot/restore")
    assert r.status_code == 404


def test_restore_brings_the_project_folder_back(tmp_path, client):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    (root / "a.txt").write_text("original")

    snap.ensure_snapshot(project, "session1")
    (root / "a.txt").write_text("edited by the agent")
    (root / "b.txt").write_text("created by the agent")

    r = client.post("/sessions/session1/snapshot/restore")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert (root / "a.txt").read_text() == "original"
    assert not (root / "b.txt").exists()


def test_deleting_a_session_discards_its_snapshot(tmp_path, client):
    project = _project(tmp_path)
    path = sessions.new_session_path()
    session_id = path.stem
    sessions.save_session(path, [])
    snap.ensure_snapshot(project, session_id)
    assert snapshots.get_snapshot(session_id) is not None

    r = client.delete(f"/sessions/{session_id}")
    assert r.status_code == 200
    assert snapshots.get_snapshot(session_id) is None
