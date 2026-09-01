"""GET /sessions/{id}/snapshots, GET .../snapshot/diff, and POST
.../snapshot/restore - the desktop app's "undo" affordance (see
triton/tools/snapshot.py for the actual git/copy logic, already covered
directly in test_snapshot.py). These tests exercise the HTTP layer on
top: an empty/404 shape when there's nothing to restore, that a restore
actually reaches the project folder end to end, and that deleting a
session or a project purges the snapshots that belonged to it."""

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
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)


@pytest.fixture
def client():
    return TestClient(server.app)


def _project(tmp_path):
    folder = tmp_path / "myproject"
    folder.mkdir()
    return projects.create_project("test-project", str(folder))


def _session_with_messages(*user_texts: str) -> str:
    path = sessions.new_session_path()
    messages = []
    for text in user_texts:
        messages.append({"role": "user", "content": text})
        messages.append({"role": "assistant", "content": "ok"})
    sessions.save_session(path, messages)
    return path.stem


# --- GET /sessions/{id}/snapshots ---


def test_list_snapshots_is_empty_when_none_exist(client):
    r = client.get("/sessions/no-such-session/snapshots")
    assert r.status_code == 200
    assert r.json() == []


def test_list_snapshots_reports_kind_and_created_at(tmp_path, client):
    project = _project(tmp_path)
    session_id = _session_with_messages("do something")
    snap.ensure_snapshot(project, session_id, 1)

    r = client.get(f"/sessions/{session_id}/snapshots")
    assert r.status_code == 200
    [point] = r.json()
    assert point["kind"] == "copy"
    assert point["turn_index"] == 1
    assert point["created_at"]


def test_list_snapshots_includes_a_preview_of_the_triggering_message(tmp_path, client):
    project = _project(tmp_path)
    session_id = _session_with_messages("add a login page", "now fix the CSS")
    snap.ensure_snapshot(project, session_id, 1)
    snap.ensure_snapshot(project, session_id, 2)

    r = client.get(f"/sessions/{session_id}/snapshots")
    points = r.json()

    assert [p["turn_index"] for p in points] == [1, 2]
    assert points[0]["message_preview"] == "add a login page"
    assert points[1]["message_preview"] == "now fix the CSS"


def test_list_snapshots_truncates_a_long_message_preview(tmp_path, client):
    project = _project(tmp_path)
    long_text = "x" * 200
    session_id = _session_with_messages(long_text)
    snap.ensure_snapshot(project, session_id, 1)

    r = client.get(f"/sessions/{session_id}/snapshots")
    preview = r.json()[0]["message_preview"]

    assert len(preview) < len(long_text)
    assert preview.endswith("...")


# --- GET /sessions/{id}/snapshot/diff ---


def test_diff_404_when_no_snapshot_for_that_turn(client):
    r = client.get("/sessions/no-such-session/snapshot/diff", params={"turn_index": 1})
    assert r.status_code == 404


def test_diff_reports_created_deleted_and_modified(tmp_path, client):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    (root / "a.txt").write_text("original")
    (root / "to_be_deleted.txt").write_text("present at snapshot time")
    session_id = _session_with_messages("do something")

    snap.ensure_snapshot(project, session_id, 1)
    (root / "a.txt").write_text("edited by the agent")
    (root / "b.txt").write_text("created by the agent")
    (root / "to_be_deleted.txt").unlink()

    r = client.get(f"/sessions/{session_id}/snapshot/diff", params={"turn_index": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == ["b.txt"]
    assert body["deleted"] == ["to_be_deleted.txt"]
    assert body["modified"] == ["a.txt"]


# --- POST /sessions/{id}/snapshot/restore ---


def test_restore_404_when_no_snapshot_for_that_turn(client):
    r = client.post("/sessions/no-such-session/snapshot/restore", json={"turn_index": 1})
    assert r.status_code == 404


def test_restore_404_when_project_was_deleted(tmp_path, client):
    project = _project(tmp_path)
    session_id = _session_with_messages("do something")
    snap.ensure_snapshot(project, session_id, 1)
    projects.delete_project(project.id)

    r = client.post(f"/sessions/{session_id}/snapshot/restore", json={"turn_index": 1})
    assert r.status_code == 404


def test_restore_brings_the_project_folder_back(tmp_path, client):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    (root / "a.txt").write_text("original")
    session_id = _session_with_messages("do something")

    snap.ensure_snapshot(project, session_id, 1)
    (root / "a.txt").write_text("edited by the agent")
    (root / "b.txt").write_text("created by the agent")

    r = client.post(f"/sessions/{session_id}/snapshot/restore", json={"turn_index": 1})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert (root / "a.txt").read_text() == "original"
    assert not (root / "b.txt").exists()


def test_restore_targets_a_specific_turn_not_only_the_first(tmp_path, client):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    session_id = _session_with_messages("turn one", "turn two")

    snap.ensure_snapshot(project, session_id, 1)
    (root / "a.txt").write_text("written during turn 1")
    snap.ensure_snapshot(project, session_id, 2)
    (root / "a.txt").write_text("written during turn 2")
    (root / "b.txt").write_text("created during turn 2")

    r = client.post(f"/sessions/{session_id}/snapshot/restore", json={"turn_index": 2})
    assert r.status_code == 200
    # only turn 2's writes are undone - turn 1's survives
    assert (root / "a.txt").read_text() == "written during turn 1"
    assert not (root / "b.txt").exists()


# --- cascading cleanup ---


def test_deleting_a_session_discards_every_turns_snapshot(tmp_path, client):
    project = _project(tmp_path)
    session_id = _session_with_messages("turn one", "turn two")
    snap.ensure_snapshot(project, session_id, 1)
    snap.ensure_snapshot(project, session_id, 2)
    assert len(snapshots.list_snapshots(session_id)) == 2

    r = client.delete(f"/sessions/{session_id}")
    assert r.status_code == 200
    assert snapshots.list_snapshots(session_id) == []


def test_deleting_a_project_discards_snapshots_from_every_session_that_wrote_to_it(
    tmp_path, client
):
    project = _project(tmp_path)
    session_a = _session_with_messages("turn one")
    session_b = _session_with_messages("turn one")
    snap.ensure_snapshot(project, session_a, 1)
    snap.ensure_snapshot(project, session_b, 1)

    r = client.delete(f"/projects/{project.id}")
    assert r.status_code == 200
    assert snapshots.list_snapshots(session_a) == []
    assert snapshots.list_snapshots(session_b) == []
