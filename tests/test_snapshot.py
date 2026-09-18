"""The write-tool safety net (triton/tools/snapshot.py): ensure_snapshot
takes a one-time-per-turn capture of a project folder before its first
write in that turn, restore_snapshot brings the folder back to exactly
that state later - one restore point per turn that actually wrote
something, not just one for the whole session (see
storage/snapshots.py's list_snapshots). Covers the current homemade
content-addressable store (used for every project, git repo or not),
the legacy git/copy formats still readable for pre-existing data, plus
the idempotency, purge, and cleanup behavior server.py/orchestrator.py
rely on."""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from triton.storage import projects, snapshots
from triton.storage.projects import Project
from triton.storage.snapshots import Snapshot
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
    monkeypatch.setattr(snap, "OBJECTS_ROOT", tmp_path / "snapshot_objects")
    monkeypatch.setattr(snap, "MANIFESTS_ROOT", tmp_path / "snapshot_manifests")
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


def test_ensure_snapshot_does_nothing_without_a_project():
    assert snap.ensure_snapshot(None, "session1", 1) is False
    assert snapshots.get_snapshot("session1", 1) is None


def test_ensure_snapshot_uses_the_content_store_even_for_a_git_repo(tmp_path):
    """The whole point of the homemade store (see the module docstring):
    a project meant to be pushed to GitHub shouldn't have the safety
    net's own bookkeeping living inside its real git object database, so
    even a git-repo project gets a "content" snapshot, not a "git" one."""
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "tracked.txt").write_text("modified before any snapshot")
    (root / "untracked.txt").write_text("new file")

    snap.ensure_snapshot(project, "session1", 1)

    record = snapshots.get_snapshot("session1", 1)
    assert record is not None
    assert record.kind == "content"
    assert record.turn_index == 1

    manifest = json.loads(Path(record.location).read_text())
    assert set(manifest) == {"tracked.txt", "untracked.txt"}

    # taking the snapshot must not have touched the real working
    # tree/index at all - it never ran any git command.
    status = subprocess.run(["git", "status", "--short"], cwd=root, capture_output=True, text=True)
    assert "tracked.txt" in status.stdout
    assert "?? untracked.txt" in status.stdout
    assert (root / "tracked.txt").read_text() == "modified before any snapshot"


def test_ensure_snapshot_is_a_noop_once_that_turn_already_has_one(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    assert snap.ensure_snapshot(project, "session1", 1) is True
    first = snapshots.get_snapshot("session1", 1)

    (root / "tracked.txt").write_text("changed after the first snapshot")
    assert snap.ensure_snapshot(project, "session1", 1) is False
    second = snapshots.get_snapshot("session1", 1)

    assert first == second


def test_ensure_snapshot_takes_a_new_one_for_a_later_turn(tmp_path):
    """The whole point of tracking turn_index: a session's second turn
    gets its own restore point instead of being silently absorbed into
    the first one."""
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    assert snap.ensure_snapshot(project, "session1", 1) is True
    (root / "tracked.txt").write_text("written during turn 1")

    assert snap.ensure_snapshot(project, "session1", 2) is True
    points = snapshots.list_snapshots("session1")
    assert [p.turn_index for p in points] == [1, 2]
    assert points[0].location != points[1].location


def test_ensure_snapshot_on_a_non_git_folder(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)

    record = snapshots.get_snapshot("session2", 1)
    assert record is not None
    assert record.kind == "content"
    manifest = json.loads(Path(record.location).read_text())
    assert set(manifest) == {"a.txt"}


def test_snapshot_ignores_regenerable_dependencies_and_build_outputs(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "source.py").write_text("print('hello')")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "package.js").write_text("generated dependency")
    (root / "dist").mkdir()
    (root / "dist" / "bundle.js").write_text("generated bundle")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)

    record = snapshots.get_snapshot("session2", 1)
    assert record is not None
    assert set(json.loads(Path(record.location).read_text())) == {"source.py"}


def test_finalize_snapshot_creates_an_immutable_after_state(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    session_id = "session-final"

    snap.ensure_snapshot(project, session_id, 1)
    (root / "tracked.txt").write_text("written during turn")
    assert snap.finalize_snapshot(project, session_id, 1) is True

    record = snapshots.get_snapshot(session_id, 1)
    assert record is not None
    assert record.after_location is not None
    assert snap.commit_diff_snapshot(record).modified == ["tracked.txt"]

    # A later modification does not alter the commit's recorded diff/content.
    (root / "tracked.txt").write_text("later external change")
    assert snap.commit_snapshot_file_content(record, "tracked.txt") == (
        "original",
        "written during turn",
    )

    snap.restore_snapshot(project, record, "after")
    assert (root / "tracked.txt").read_text() == "written during turn"


def test_content_store_dedupes_identical_file_content(tmp_path):
    """Two turns (even across different projects) that happen to write
    the exact same bytes to a file must only cost one blob on disk -
    that's the whole point of hashing by content instead of copying the
    whole tree every time (see the module docstring)."""
    root1 = tmp_path / "p1"
    root1.mkdir()
    (root1 / "shared.txt").write_text("same content everywhere")
    project1 = Project(id="proj1", name="p1", folder_path=str(root1))

    root2 = tmp_path / "p2"
    root2.mkdir()
    (root2 / "shared.txt").write_text("same content everywhere")
    project2 = Project(id="proj2", name="p2", folder_path=str(root2))

    snap.ensure_snapshot(project1, "session1", 1)
    snap.ensure_snapshot(project2, "session2", 1)

    blobs = list(snap.OBJECTS_ROOT.glob("*/*"))
    assert len(blobs) == 1


def test_restore_content_snapshot_undoes_every_change_since(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "to_be_deleted.txt").write_text("present at snapshot time")

    snap.ensure_snapshot(project, "session1", 1)
    snapshot = snapshots.get_snapshot("session1", 1)
    assert snapshot is not None

    # a turn's worth of writes after the snapshot: a modification, a new
    # file, and a deletion of a file that existed at snapshot time
    (root / "tracked.txt").write_text("edited by the agent")
    (root / "created_by_agent.txt").write_text("new")
    (root / "to_be_deleted.txt").unlink()

    snap.restore_snapshot(project, snapshot)

    assert (root / "tracked.txt").read_text() == "original"
    assert not (root / "created_by_agent.txt").exists()
    assert (root / "to_be_deleted.txt").read_text() == "present at snapshot time"


def test_restore_content_snapshot_on_a_non_git_folder(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("original")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)
    snapshot = snapshots.get_snapshot("session2", 1)
    assert snapshot is not None

    (root / "a.txt").write_text("edited")
    (root / "b.txt").write_text("new")

    snap.restore_snapshot(project, snapshot)

    assert (root / "a.txt").read_text() == "original"
    assert not (root / "b.txt").exists()


def test_restore_to_an_earlier_turn_also_undoes_a_later_turns_writes(tmp_path):
    """Restoring to turn 1's snapshot undoes turn 2's writes too - turn 2
    happened after it, so its own restore point is irrelevant here, only
    the target turn's captured state matters."""
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    snap.ensure_snapshot(project, "session1", 1)
    (root / "tracked.txt").write_text("written during turn 1")
    snap.ensure_snapshot(project, "session1", 2)
    (root / "tracked.txt").write_text("written during turn 2")
    (root / "turn2.txt").write_text("created during turn 2")

    turn1_snapshot = snapshots.get_snapshot("session1", 1)
    assert turn1_snapshot is not None
    snap.restore_snapshot(project, turn1_snapshot)

    assert (root / "tracked.txt").read_text() == "original"
    assert not (root / "turn2.txt").exists()


def test_restore_to_the_most_recent_turn_only_undoes_that_turn(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    snap.ensure_snapshot(project, "session1", 1)
    (root / "tracked.txt").write_text("written during turn 1")
    snap.ensure_snapshot(project, "session1", 2)
    (root / "tracked.txt").write_text("written during turn 2")
    (root / "turn2.txt").write_text("created during turn 2")

    turn2_snapshot = snapshots.get_snapshot("session1", 2)
    assert turn2_snapshot is not None
    snap.restore_snapshot(project, turn2_snapshot)

    # turn 1's write survives - only turn 2's own writes are undone
    assert (root / "tracked.txt").read_text() == "written during turn 1"
    assert not (root / "turn2.txt").exists()


def test_diff_content_snapshot_classifies_every_change(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "to_be_deleted.txt").write_text("present at snapshot time")
    (root / "untouched.txt").write_text("never changes")

    snap.ensure_snapshot(project, "session1", 1)
    snapshot = snapshots.get_snapshot("session1", 1)
    assert snapshot is not None

    (root / "tracked.txt").write_text("edited by the agent")
    (root / "created_by_agent.txt").write_text("new")
    (root / "to_be_deleted.txt").unlink()

    diff = snap.diff_snapshot(project, snapshot)

    assert diff.created == ["created_by_agent.txt"]
    assert diff.deleted == ["to_be_deleted.txt"]
    assert diff.modified == ["tracked.txt"]


def test_diff_content_snapshot_with_no_changes_is_empty(tmp_path):
    project = _git_repo(tmp_path)
    snap.ensure_snapshot(project, "session1", 1)
    snapshot = snapshots.get_snapshot("session1", 1)
    assert snapshot is not None

    diff = snap.diff_snapshot(project, snapshot)

    assert diff.created == []
    assert diff.deleted == []
    assert diff.modified == []


def test_discard_snapshot_removes_every_turns_record_and_manifest(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    snap.ensure_snapshot(project, "session2", 1)
    snap.ensure_snapshot(project, "session2", 2)
    records = snapshots.list_snapshots("session2")
    assert len(records) == 2
    manifest_paths = [Path(r.location) for r in records]
    assert all(p.is_file() for p in manifest_paths)

    snap.discard_snapshot("session2")

    assert snapshots.list_snapshots("session2") == []
    assert not any(p.exists() for p in manifest_paths)


def test_discard_snapshot_garbage_collects_now_unreferenced_blobs(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    snap.ensure_snapshot(project, "session2", 1)
    assert len(list(snap.OBJECTS_ROOT.glob("*/*"))) == 1

    snap.discard_snapshot("session2")

    assert list(snap.OBJECTS_ROOT.glob("*/*")) == []


def test_discard_snapshot_keeps_a_blob_still_referenced_by_another_snapshot(tmp_path):
    """A blob shared by two snapshots must survive discarding only one of
    them - GC only removes what nothing references anymore."""
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("shared content")
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    snap.ensure_snapshot(project, "session-a", 1)
    snap.ensure_snapshot(project, "session-b", 1)
    assert len(list(snap.OBJECTS_ROOT.glob("*/*"))) == 1

    snap.discard_snapshot("session-a")

    assert list(snap.OBJECTS_ROOT.glob("*/*")) != []
    remaining = snapshots.get_snapshot("session-b", 1)
    assert remaining is not None
    snap.diff_snapshot(project, remaining)  # still restorable


def test_discard_snapshots_for_project_purges_every_session_that_wrote_to_it(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    snap.ensure_snapshot(project, "session-a", 1)
    snap.ensure_snapshot(project, "session-b", 1)
    other_project = Project(id="other", name="other", folder_path=str(tmp_path / "other"))
    (tmp_path / "other").mkdir()
    projects.save_projects([project, other_project])
    snap.ensure_snapshot(other_project, "session-c", 1)

    removed = snap.discard_snapshots_for_project("proj2")

    assert removed == 2
    assert snapshots.list_snapshots("session-a") == []
    assert snapshots.list_snapshots("session-b") == []
    assert len(snapshots.list_snapshots("session-c")) == 1


def test_purge_expired_snapshots_removes_only_old_ones(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session-old", 1)
    snap.ensure_snapshot(project, "session-new", 1)

    old_record = snapshots.get_snapshot("session-old", 1)
    assert old_record is not None
    stale = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    snapshots.save_snapshot(
        Snapshot(
            session_id=old_record.session_id,
            project_id=old_record.project_id,
            kind=old_record.kind,
            location=old_record.location,
            created_at=stale,
            turn_index=old_record.turn_index,
        )
    )

    removed = snap.purge_expired_snapshots(max_age_days=30)

    assert removed == 1
    assert snapshots.list_snapshots("session-old") == []
    assert len(snapshots.list_snapshots("session-new")) == 1


def test_old_dict_format_snapshots_json_is_migrated_in_place(tmp_path):
    """Real snapshots.json files exist from before turn-tracking was
    added: {session_id: record}, one snapshot per session. Must not
    crash on load - migrated to the new list format (turn_index=1,
    equivalent to what a whole-session snapshot always meant) and
    re-saved so this only runs once."""
    old_format = {
        "2026-08-31_182628": {
            "session_id": "2026-08-31_182628",
            "project_id": "proj1",
            "kind": "copy",
            "location": "/tmp/somewhere",
            "created_at": "2026-08-31T16:27:00.081846+00:00",
        }
    }
    snapshots.SNAPSHOTS_FILE.write_text(json.dumps(old_format))

    points = snapshots.list_snapshots("2026-08-31_182628")

    assert len(points) == 1
    assert points[0].turn_index == 1
    assert points[0].location == "/tmp/somewhere"

    # re-saved in the new list format - a second read must not re-migrate
    # (and must not choke on the now-list-shaped file)
    raw = snapshots.SNAPSHOTS_FILE.read_text()
    assert raw.strip().startswith("[")
    assert snapshots.list_snapshots("2026-08-31_182628") == points


def test_write_tool_names_covers_the_mutating_tools():
    assert {
        "write_file",
        "edit_file",
        "delete_file",
        "move_file",
        "git_commit",
        "git_checkout",
    } == snap.WRITE_TOOL_NAMES


# --- legacy "git"/"copy" formats: no longer produced, but must stay
# restorable/diffable/discardable for any snapshot already on disk from
# before the content store existed (see the module docstring).


def test_restore_snapshot_still_supports_a_legacy_git_record(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    (root / "to_be_deleted.txt").write_text("present at snapshot time")

    sha = snap._take_git_snapshot(root, "session1", 1)
    assert sha is not None
    snapshot = Snapshot(
        session_id="session1",
        project_id=project.id,
        kind="git",
        location=sha,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )
    snapshots.save_snapshot(snapshot)

    (root / "tracked.txt").write_text("edited by the agent")
    (root / "created_by_agent.txt").write_text("new")
    (root / "to_be_deleted.txt").unlink()

    snap.restore_snapshot(project, snapshot)

    assert (root / "tracked.txt").read_text() == "original"
    assert not (root / "created_by_agent.txt").exists()
    assert (root / "to_be_deleted.txt").read_text() == "present at snapshot time"

    diff = snap.diff_snapshot(project, snapshot)
    assert diff.created == []
    assert diff.deleted == []
    assert diff.modified == []


def test_restore_snapshot_still_supports_a_legacy_copy_record(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("original")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    location = snap._take_copy_snapshot(root, "session2", 1)
    snapshot = Snapshot(
        session_id="session2",
        project_id=project.id,
        kind="copy",
        location=location,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )
    snapshots.save_snapshot(snapshot)

    (root / "a.txt").write_text("edited")
    (root / "b.txt").write_text("new")

    diff = snap.diff_snapshot(project, snapshot)
    assert diff.created == ["b.txt"]
    assert diff.modified == ["a.txt"]

    snap.restore_snapshot(project, snapshot)

    assert (root / "a.txt").read_text() == "original"
    assert not (root / "b.txt").exists()


def test_discard_one_still_cleans_up_a_legacy_git_ref(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"
    projects.save_projects([project])

    sha = snap._take_git_snapshot(root, "session1", 1)
    assert sha is not None
    snapshot = Snapshot(
        session_id="session1",
        project_id=project.id,
        kind="git",
        location=sha,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )
    snapshots.save_snapshot(snapshot)

    snap.discard_snapshot("session1")

    ref = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", snap._snapshot_ref("session1", 1)],
        cwd=root,
    )
    assert ref.returncode != 0


def test_discard_one_still_cleans_up_a_legacy_copy_backup(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("hello")
    project = Project(id="proj2", name="plain", folder_path=str(root))
    projects.save_projects([project])

    location = snap._take_copy_snapshot(root, "session2", 1)
    snapshot = Snapshot(
        session_id="session2",
        project_id=project.id,
        kind="copy",
        location=location,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )
    snapshots.save_snapshot(snapshot)

    snap.discard_snapshot("session2")

    assert not Path(location).exists()


# --- snapshot_file_content (per-file before/after for the history browser) ---


def test_snapshot_file_content_reports_old_and_new_for_a_modified_file(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("original")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)
    snapshot = snapshots.get_snapshot("session2", 1)
    assert snapshot is not None

    (root / "a.txt").write_text("edited")

    old, new = snap.snapshot_file_content(project, snapshot, "a.txt")
    assert old == "original"
    assert new == "edited"


def test_snapshot_file_content_reports_no_old_for_a_created_file(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)
    snapshot = snapshots.get_snapshot("session2", 1)
    assert snapshot is not None

    (root / "new_file.txt").write_text("created after the snapshot")

    old, new = snap.snapshot_file_content(project, snapshot, "new_file.txt")
    assert old is None
    assert new == "created after the snapshot"


def test_snapshot_file_content_reports_no_new_for_a_deleted_file(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "gone.txt").write_text("present at snapshot time")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)
    snapshot = snapshots.get_snapshot("session2", 1)
    assert snapshot is not None

    (root / "gone.txt").unlink()

    old, new = snap.snapshot_file_content(project, snapshot, "gone.txt")
    assert old == "present at snapshot time"
    assert new is None


def test_content_snapshots_do_not_follow_symlinks_outside_the_project(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("must not be captured")
    (root / "outside-link.txt").symlink_to(secret)
    project = Project(id="proj2", name="plain", folder_path=str(root))

    snap.ensure_snapshot(project, "session2", 1)
    snapshot = snapshots.get_snapshot("session2", 1)
    assert snapshot is not None

    assert "outside-link.txt" not in snap._load_manifest(snapshot.location)


def test_snapshot_file_content_supports_a_legacy_git_record(tmp_path):
    project = _git_repo(tmp_path)
    root = tmp_path / "repo"

    sha = snap._take_git_snapshot(root, "session1", 1)
    assert sha is not None
    snapshot = Snapshot(
        session_id="session1",
        project_id=project.id,
        kind="git",
        location=sha,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )

    (root / "tracked.txt").write_text("edited")

    old, new = snap.snapshot_file_content(project, snapshot, "tracked.txt")
    assert old == "original"
    assert new == "edited"


def test_snapshot_file_content_supports_a_legacy_copy_record(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.txt").write_text("original")
    project = Project(id="proj2", name="plain", folder_path=str(root))

    location = snap._take_copy_snapshot(root, "session2", 1)
    snapshot = Snapshot(
        session_id="session2",
        project_id=project.id,
        kind="copy",
        location=location,
        created_at=datetime.now(UTC).isoformat(),
        turn_index=1,
    )

    (root / "a.txt").write_text("edited")

    old, new = snap.snapshot_file_content(project, snapshot, "a.txt")
    assert old == "original"
    assert new == "edited"
