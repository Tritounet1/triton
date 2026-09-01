"""Memory has three scopes now, replacing the single flat memory.md:
global (storage/memory.py, shared by every conversation), per-project
(storage/projects.py, shared by every conversation in the same project,
current and future), and per-session (storage/sessions.py, private to one
project-less conversation). remember (tools/memory.py) picks which of the
last two to write to; build_system_message (llm/chat_loop.py) reads all
three back into the system prompt."""

import uuid
from typing import cast

import pytest

from triton.llm.chat_loop import build_system_message
from triton.storage import memory as global_memory
from triton.storage import projects, sessions
from triton.tools.memory import remember


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    monkeypatch.setattr(projects, "PROJECT_MEMORY_DIR", tmp_path / "project_memory")
    monkeypatch.setattr(global_memory, "GLOBAL_MEMORY_FILE", tmp_path / "memory_global.md")


def _session(project_id: str | None = None) -> str:
    # a unique id per call, not new_session_path()'s second-granularity
    # timestamp - two calls in the same test can otherwise collide (see
    # test_session_model_and_cost.py for the same fix).
    session_id = uuid.uuid4().hex
    sessions.SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    sessions.save_session(sessions.session_path(session_id), [])
    if project_id:
        sessions.save_session_project(session_id, project_id)
    return session_id


# --- remember: which file it writes to ---


def test_remember_without_a_project_writes_to_session_memory():
    session_id = _session()
    remember("likes tabs over spaces", session_id=session_id)

    assert sessions.load_session_memory(session_id) == "- likes tabs over spaces"


def test_remember_with_a_project_writes_to_project_memory_not_session():
    project = projects.create_project("demo", "/tmp/demo")
    session_id = _session(project_id=project.id)

    remember("uses pnpm, not npm", session_id=session_id)

    assert projects.load_project_memory(project.id) == "- uses pnpm, not npm"
    assert sessions.load_session_memory(session_id) == ""


def test_remember_in_two_sessions_of_the_same_project_shares_memory():
    project = projects.create_project("demo", "/tmp/demo")
    session_a = _session(project_id=project.id)
    session_b = _session(project_id=project.id)

    remember("fact from conversation A", session_id=session_a)
    remember("fact from conversation B", session_id=session_b)

    combined = projects.load_project_memory(project.id)
    assert "fact from conversation A" in combined
    assert "fact from conversation B" in combined


def test_remember_in_two_project_less_sessions_stays_private_to_each():
    session_a = _session()
    session_b = _session()

    remember("only in A", session_id=session_a)

    assert "only in A" in sessions.load_session_memory(session_a)
    assert sessions.load_session_memory(session_b) == ""


def test_delete_session_removes_its_memory_but_not_its_project_s():
    project = projects.create_project("demo", "/tmp/demo")
    session_id = _session(project_id=project.id)
    remember("project fact", session_id=session_id)

    sessions.delete_session(session_id)

    assert projects.load_project_memory(project.id) == "- project fact"


# --- build_system_message: what gets assembled into the prompt ---


def _content(session_id: str, project: projects.Project | None = None) -> str:
    return cast(str, build_system_message(session_id, project).get("content"))


def test_system_message_has_no_memory_section_when_everything_is_empty():
    session_id = _session()
    assert "Facts" not in _content(session_id)


def test_system_message_includes_global_memory_regardless_of_scope():
    global_memory.GLOBAL_MEMORY_FILE.write_text("- always tell the truth\n")
    session_id = _session()

    content = _content(session_id)

    assert "shared across all conversations" in content
    assert "always tell the truth" in content


def test_system_message_uses_session_memory_without_a_project():
    session_id = _session()
    sessions.append_session_memory(session_id, "prefers dark mode")

    content = _content(session_id)

    assert "remembered in this conversation" in content
    assert "prefers dark mode" in content


def test_system_message_uses_project_memory_with_a_project():
    project = projects.create_project("demo", "/tmp/demo")
    session_id = _session(project_id=project.id)
    projects.append_project_memory(project.id, "uses conventional commits")

    content = _content(session_id, project)

    assert "shared across every conversation in this project" in content
    assert "uses conventional commits" in content


def test_system_message_with_a_project_never_shows_that_session_s_own_memory():
    """A project-scoped conversation's memory IS the project's memory -
    nothing should ever land in its own session memory file to begin
    with (see test_remember_with_a_project_writes_to_project_memory_not_session),
    but this pins down that build_system_message doesn't read it even if
    something did."""
    project = projects.create_project("demo", "/tmp/demo")
    session_id = _session(project_id=project.id)
    sessions.append_session_memory(session_id, "should never surface")

    content = _content(session_id, project)

    assert "should never surface" not in content
