"""The /remember slash command's two backends:

- POST /sessions/{id}/remember ("/remember session <note>"): reuses the
  remember tool itself, so it lands wherever a model-issued remember call
  for that session would - the project's memory if one is linked,
  otherwise that session's own (see test_memory.py for the scoping logic
  itself, already covered there via the remember tool directly).
- POST /memory/global ("/remember global <note>"): the only writer of
  the global tier - the remember tool never writes there itself.
"""

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import memory as global_memory
from triton.storage import projects, sessions


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "PROJECT_MEMORY_DIR", tmp_path / "project_memory")
    monkeypatch.setattr(global_memory, "GLOBAL_MEMORY_FILE", tmp_path / "memory_global.md")


@pytest.fixture
def client():
    return TestClient(server.app)


def _session(project_id: str | None = None) -> str:
    path = sessions.new_session_path()
    sessions.save_session(path, [])
    session_id = path.stem
    if project_id:
        sessions.save_session_project(session_id, project_id)
    return session_id


def test_remember_session_without_a_project(client):
    session_id = _session()

    r = client.post(f"/sessions/{session_id}/remember", json={"note": "likes tabs"})

    assert r.status_code == 200
    assert sessions.load_session_memory(session_id) == "- likes tabs"


def test_remember_session_with_a_project_writes_to_project_memory(client):
    project = projects.create_project("demo", "/tmp/demo")
    session_id = _session(project_id=project.id)

    r = client.post(f"/sessions/{session_id}/remember", json={"note": "uses pnpm"})

    assert r.status_code == 200
    assert projects.load_project_memory(project.id) == "- uses pnpm"
    assert sessions.load_session_memory(session_id) == ""


def test_remember_session_404_for_unknown_session(client):
    r = client.post("/sessions/does-not-exist/remember", json={"note": "x"})
    assert r.status_code == 404


def test_remember_global(client):
    r = client.post("/memory/global", json={"note": "always be concise"})

    assert r.status_code == 200
    assert global_memory.load_global_memory() == "- always be concise"


def test_remember_global_appends_multiple_notes(client):
    client.post("/memory/global", json={"note": "first"})
    client.post("/memory/global", json={"note": "second"})

    content = global_memory.load_global_memory()
    assert "first" in content
    assert "second" in content
