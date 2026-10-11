import os
from datetime import UTC, datetime, timedelta

import server
from triton.deployment import DeploymentProfile
from triton.storage.projects import Project


def test_global_search_finds_content_and_sorts_recent_items(tmp_path, monkeypatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    source_file = project_dir / "notes.txt"
    source_file.write_text("needle in a project file")
    session_file = tmp_path / "session.json"
    session_file.write_text("[]")
    global_memory = tmp_path / "memory_global.md"
    global_memory.write_text("needle in global memory")
    project_memory = tmp_path / "project-memory.md"
    project_memory.write_text("recent project note")
    now = datetime.now(UTC)
    os.utime(global_memory, (now.timestamp() - 20, now.timestamp() - 20))
    os.utime(project_memory, (now.timestamp(), now.timestamp()))

    project = Project(id="project-1", name="Project", folder_path=str(project_dir))
    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.DESKTOP)
    monkeypatch.setattr(server, "load_projects", lambda: [project])
    monkeypatch.setattr(server, "list_session_ids", lambda: ["session-1"])
    monkeypatch.setattr(server, "load_session_project", lambda _: "project-1")
    monkeypatch.setattr(server, "load_title", lambda _: "Needle conversation")
    monkeypatch.setattr(server, "storage_session_path", lambda _: session_file)
    monkeypatch.setattr(server, "session_memory_path", lambda _: tmp_path / "session-memory.md")
    monkeypatch.setattr(server, "project_memory_path", lambda _: project_memory)
    monkeypatch.setattr(server, "GLOBAL_MEMORY_FILE", global_memory)
    monkeypatch.setattr(server, "_session_search_text", lambda _: "needle in conversation content")
    monkeypatch.setattr(server.background_tasks, "list_tasks", lambda: [])

    matches = server.global_search(q="needle")

    assert {match["kind"] for match in matches} == {"conversation", "file", "memory"}
    assert all("needle" in f"{match['title']} {match['excerpt']}".lower() for match in matches)

    recent = server.global_search()

    assert recent[0]["title"] == "Mémoire : Project"
    assert all(
        datetime.fromisoformat(str(item["modified_at"])) >= now - timedelta(minutes=1)
        for item in recent
    )
