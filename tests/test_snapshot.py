"""The write-tool safety net (triton/tools/snapshot.py): ensure_snapshot
takes a one-time-per-session capture of a project folder before its first
write, restore_snapshot brings the folder back to exactly that state
later. Covers both backends - a git repo (the scratch-index commit
approach, chosen after git stash create turned out to silently ignore
--include-untracked) and a plain folder (the non-git fallback) - plus the
idempotency and cleanup behavior server.py/orchestrator.py rely on."""

import subprocess
from pathlib import Path

import pytest

from triton.storage import projects, snapshots
from triton.storage.projects import Project
from triton.tools import snapshot as snap


def _git(args: list[str], cwd) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def _git_repo(tmp_path) -> Project:
    root = tmp_path / "repo"
    root.mkdir()
    _git(["init", "-q"], root)
    _git(["config", "user.email", "test@example.com"], root)
    _git(["config", "user.name", "Test"], root)
    (root / "tracked.txt").write_text("original")
    _git(["add", "tracked.txt"], root)
    _git(["commit", "-q", "-m", "init"], root)
    return Project(id="proj1", name="repo", folder_path=str(root))


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshots, "SNAPSHOTS_FILE", tmp_path / "snapshots.json")
    monkeypatch.setattr(snap, "BACKUP_ROOT", tmp_path / "snapshot_backups")
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


def test_ensure_snapshot_does_nothing_without_a_project():
    snap.ensure_snapshot(None, "session1")
    assert snapshots.get_snapshot("session1") is None


def test_ensure_snapshot_on_a_git_repo_captures_tracked_and_untracked_changes(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "tracked.txt").write_text("modified before any snapshot")
    (root / "untracked.txt").write_text("new file")

    snap.ensure_snapshot(project, "session1")

    record = snapshots.get_snapshot("session1")
    assert record is not None
    assert record.kind == "git"

    tree = subprocess.run(
        ["git", "ls-tree", "-r", record.location, "--name-only"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert "tracked.txt" in tree.stdout
    assert "untracked.txt" in tree.stdout

    # taking the snapshot must not have touched the real working tree/index
    status = subprocess.run(["git", "status", "--short"], cwd=root, capture_output=True, text=True)
    assert "tracked.txt" in status.stdout
    assert "?? untracked.txt" in status.stdout
    assert (root / "tracked.txt").read_text() == "modified before any snapshot"


def test_ensure_snapshot_is_a_noop_once_a_session_already_has_one(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    snap.ensure_snapshot(project, "session1")
    first = snapshots.get_snapshot("session1")

    (root / "tracked.txt").write_text("changed after the first snapshot")
    snap.ensure_snapshot(project, "session1")
    second = snapshots.get_snapshot("session1")

    assert first == second


def test_ensure_snapshot_on_a_non_git_folder_copies_it(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2")

    record = snapshots.get_snapshot("session2")
    assert record is not None
    assert record.kind == "copy"
    backup = Path(record.location)
    assert (backup / "a.txt").read_text() == "hello"


def test_restore_snapshot_on_a_git_repo_undoes_every_change_since(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "to_be_deleted.txt").write_text("present at snapshot time")

    snap.ensure_snapshot(project, "session1")
    snapshot = snapshots.get_snapshot("session1")
    assert snapshot is not None

    # a session's worth of writes after the snapshot: a modification, a
    # new file, and a deletion of a file that existed at snapshot time
    (root / "tracked.txt").write_text("edited by the agent")
    (root / "created_by_agent.txt").write_text("new")
    (root / "to_be_deleted.txt").unlink()

    snap.restore_snapshot(project, snapshot)

    assert (root / "tracked.txt").read_text() == "original"
    assert not (root / "created_by_agent.txt").exists()
    assert (root / "to_be_deleted.txt").read_text() == "present at snapshot time"


def test_restore_snapshot_on_a_non_git_folder_undoes_every_change_since(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("original")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2")
    snapshot = snapshots.get_snapshot("session2")
    assert snapshot is not None

    (root / "a.txt").write_text("edited")
    (root / "b.txt").write_text("new")

    snap.restore_snapshot(project, snapshot)

    assert (root / "a.txt").read_text() == "original"
    assert not (root / "b.txt").exists()


def test_discard_snapshot_removes_the_record_and_the_backup(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    snap.ensure_snapshot(project, "session2")
    record = snapshots.get_snapshot("session2")
    assert record is not None
    backup_dir = Path(record.location)
    assert backup_dir.is_dir()

    snap.discard_snapshot("session2")

    assert snapshots.get_snapshot("session2") is None
    assert not backup_dir.exists()


def test_write_tool_names_covers_the_four_mutating_file_tools():
    assert {"write_file", "edit_file", "delete_file", "move_file"} == snap.WRITE_TOOL_NAMES
