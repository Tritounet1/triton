"""Automatic safety net for the write tools (write_file/edit_file/
delete_file/move_file/git_commit): the first time one is about to run in
a given turn of a project-scoped session, that turn's starting state is
captured - a dangling git commit if the folder is a git repo, or a plain
recursive copy otherwise (see the module docstring's two halves below).
One snapshot per (session, turn) - ensure_snapshot is a no-op once a
record exists for that specific turn_index, taken lazily on the first
write of the turn rather than eagerly, since most turns never write
anything - so a session accumulates one restore point per turn that
actually wrote something, letting a restore target either "undo the last
turn" or "undo everything back to the first write" (see
storage/snapshots.py's list_snapshots), not only the latter like before
turns were tracked individually.

Used from both server.py (normal conversation, behind the existing
per-call confirmation) and agents/orchestrator.py (the unsupervised
"code" subtask role, called out in that module's own docstring as having
no safety net beyond the project sandbox until this existed) - the two
places a write tool can actually run.

Git snapshots: `git stash create` looks like the obvious primitive here,
but it silently ignores --include-untracked (verified against git
2.50), so a new file the model is about to edit wouldn't be covered.
Instead this builds the tree by hand in a scratch index (GIT_INDEX_FILE
pointed at a throwaway path): `git add -A` there stages tracked and
untracked content into *that* index only, never touching the repo's real
index or working tree, then `write-tree`/`commit-tree` turn it into a
real (if unreachable) commit object. A ref under
refs/triton/snapshots/<session_id>/<turn_index> keeps that commit from
being garbage-collected."""

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from triton.paths import ROOT_DIR
from triton.storage.projects import Project, get_project
from triton.storage.snapshots import (
    Snapshot,
    delete_expired_snapshots,
    delete_snapshots_for_project,
    delete_snapshots_for_session,
    get_snapshot,
    save_snapshot,
)

# git_commit is included even though it doesn't touch the working tree
# itself: it still changes the repo's state (a new commit on the current
# branch), and until now had only the one-off confirmation prompt as a
# safeguard. Note the resulting restore is still working-tree-only (see
# restore_snapshot): checking the snapshot ref back out brings files back
# to their pre-session content, but doesn't move the branch pointer, so a
# commit the model made stays in history - undoing that fully still needs
# a manual `git reset`/`git revert`, this only guarantees the file
# contents are recoverable in one action.
WRITE_TOOL_NAMES = {"write_file", "edit_file", "delete_file", "move_file", "git_commit"}

BACKUP_ROOT = ROOT_DIR / "snapshot_backups"

# guards ensure_snapshot's read-then-write against two write tool calls
# landing at nearly the same moment - most plausibly two "code" subtasks
# in the same orchestrator run, writing to the same project from
# parallel threads (see agents/orchestrator.py's _run).
_LOCK = threading.Lock()


class RestoreError(Exception):
    pass


def _git(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env} if env else None
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15, env=full_env
    )


def _is_git_repo(root: Path) -> bool:
    return (root / ".git").exists()


def _snapshot_ref(session_id: str, turn_index: int) -> str:
    return f"refs/triton/snapshots/{session_id}/{turn_index}"


def _take_git_snapshot(root: Path, session_id: str, turn_index: int) -> str | None:
    """Builds a commit representing the working tree's current state
    (tracked changes + untracked files, respecting .gitignore, exactly
    what `git add -A` would stage) without touching the repo's real index
    or working tree - see the module docstring for why not `git stash
    create`. Returns None (snapshot skipped) if the repo has no commits
    yet to anchor a scratch index against, or if any git call fails; the
    write this was guarding shouldn't be blocked by a best-effort safety
    net misfiring."""
    head = _git(["rev-parse", "HEAD"], root)
    if head.returncode != 0:
        return None
    head_sha = head.stdout.strip()

    scratch_index = Path(tempfile.gettempdir()) / f"triton-snapshot-index-{uuid.uuid4().hex}"
    try:
        env = {"GIT_INDEX_FILE": str(scratch_index)}
        added = _git(["add", "-A"], root, env=env)
        if added.returncode != 0:
            return None
        tree = _git(["write-tree"], root, env=env)
        if tree.returncode != 0 or not tree.stdout.strip():
            return None
        tree_sha = tree.stdout.strip()

        commit = _git(["commit-tree", tree_sha, "-p", head_sha, "-m", "triton auto-snapshot"], root)
        if commit.returncode != 0 or not commit.stdout.strip():
            return None
        commit_sha = commit.stdout.strip()

        ref = _git(["update-ref", _snapshot_ref(session_id, turn_index), commit_sha], root)
        if ref.returncode != 0:
            return None
        return commit_sha
    finally:
        scratch_index.unlink(missing_ok=True)


def _take_copy_snapshot(root: Path, session_id: str, turn_index: int) -> str:
    backup_dir = BACKUP_ROOT / session_id / str(turn_index)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, backup_dir, ignore=shutil.ignore_patterns(".git"))
    return str(backup_dir)


def ensure_snapshot(project: Project | None, session_id: str, turn_index: int) -> bool:
    """Takes a snapshot of the project folder if this turn hasn't had one
    yet (turn_index: the nth user message in this session, 1-based - see
    server.py's run_chat_stream). Silently does nothing without a
    project, for a turn that already has a snapshot, or if the snapshot
    attempt itself fails (a missing/broken git binary shouldn't block the
    write the model was actually trying to make - this is a best-effort
    safety net, not a precondition for writing). Returns whether a
    snapshot was actually just taken by this call - server.py's
    run_chat_stream uses this to surface a one-time "safety net is now
    active [for this turn]" notice in the conversation itself instead of
    only in the project file panel (see SnapshotSection.tsx), which
    required knowing the feature existed at all to go find it."""
    if project is None:
        return False

    with _LOCK:
        if get_snapshot(session_id, turn_index) is not None:
            return False

        root = Path(project.folder_path).resolve()
        if not root.is_dir():
            return False

        try:
            if _is_git_repo(root):
                sha = _take_git_snapshot(root, session_id, turn_index)
                if sha is None:
                    return False
                snapshot = Snapshot(
                    session_id=session_id,
                    project_id=project.id,
                    kind="git",
                    location=sha,
                    created_at=datetime.now(UTC).isoformat(),
                    turn_index=turn_index,
                )
            else:
                location = _take_copy_snapshot(root, session_id, turn_index)
                snapshot = Snapshot(
                    session_id=session_id,
                    project_id=project.id,
                    kind="copy",
                    location=location,
                    created_at=datetime.now(UTC).isoformat(),
                    turn_index=turn_index,
                )
        except OSError:
            return False

        save_snapshot(snapshot)
        return True


def restore_snapshot(project: Project, snapshot: Snapshot) -> None:
    """Brings the project folder back to exactly the state ensure_snapshot
    captured. Only ever called from the explicit, user-confirmed restore
    endpoint (see server.py) - never automatically."""
    root = Path(project.folder_path).resolve()

    if snapshot.kind == "git":
        checkout = _git(["checkout", snapshot.location, "--", "."], root)
        if checkout.returncode != 0:
            raise RestoreError(checkout.stderr.strip() or "git checkout failed")
        # removes files created after the snapshot: checkout only
        # restores/overwrites paths present in the snapshot's tree, it
        # doesn't delete newer ones. Respects .gitignore like any other
        # git clean, so a session's git-ignored build artifacts aren't
        # swept up along with what it actually wrote.
        clean = _git(["clean", "-fd"], root)
        if clean.returncode != 0:
            raise RestoreError(clean.stderr.strip() or "git clean failed")
        # checkout ... -- . stages what it restores; unstage so the
        # working tree ends up classified (modified/untracked) exactly
        # as it was when the snapshot was taken, not as freshly staged.
        _git(["reset"], root)
    else:
        backup_dir = Path(snapshot.location)
        if not backup_dir.is_dir():
            raise RestoreError(f"backup no longer exists: {backup_dir}")
        for entry in root.iterdir():
            if entry.name == ".git":
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        for entry in backup_dir.iterdir():
            dest = root / entry.name
            if entry.is_dir():
                shutil.copytree(entry, dest)
            else:
                shutil.copy2(entry, dest)


@dataclass
class SnapshotDiff:
    """What restore_snapshot would actually do, from the session's own
    point of view rather than the snapshot's: a path this session created
    (didn't exist at snapshot time, exists now - restore deletes it), one
    it deleted (existed then, doesn't now - restore recreates it), or one
    it modified (exists both times with different content - restore
    reverts it). Paths are relative to the project folder."""

    created: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)


def _diff_git_snapshot(root: Path, snapshot_sha: str) -> SnapshotDiff:
    """Same scratch-index trick as _take_git_snapshot (see the module
    docstring): builds a tree object for the working tree's current state
    without touching the real index, then `git diff --name-status` against
    the snapshot to classify every path that changed since. No rename
    detection (`-M`) - a rename shows up as a delete + a create, which is
    still an accurate (if less elegant) description of what restore would
    do to those two paths."""
    scratch_index = Path(tempfile.gettempdir()) / f"triton-snapshot-diff-{uuid.uuid4().hex}"
    try:
        env = {"GIT_INDEX_FILE": str(scratch_index)}
        added = _git(["add", "-A"], root, env=env)
        if added.returncode != 0:
            raise RestoreError(added.stderr.strip() or "git add failed")
        tree = _git(["write-tree"], root, env=env)
        if tree.returncode != 0 or not tree.stdout.strip():
            raise RestoreError(tree.stderr.strip() or "git write-tree failed")
        current_tree_sha = tree.stdout.strip()
    finally:
        scratch_index.unlink(missing_ok=True)

    diff = _git(["diff", "--name-status", snapshot_sha, current_tree_sha], root)
    if diff.returncode != 0:
        raise RestoreError(diff.stderr.strip() or "git diff failed")

    result = SnapshotDiff()
    for line in diff.stdout.splitlines():
        if not line.strip():
            continue
        status, _, path = line.partition("\t")
        # status can carry a similarity score (e.g. "M100") - only the
        # first letter matters here
        if status[:1] == "A":
            result.created.append(path)
        elif status[:1] == "D":
            result.deleted.append(path)
        else:
            result.modified.append(path)
    return result


def _diff_copy_snapshot(root: Path, backup_dir: Path) -> SnapshotDiff:
    """Walks both trees and compares file content directly - no git
    machinery available for the non-git backend, and these backups are
    already a full recursive copy (see _take_copy_snapshot), so the trees
    involved are assumed small enough for this to be cheap."""
    if not backup_dir.is_dir():
        raise RestoreError(f"backup no longer exists: {backup_dir}")

    def relative_files(base: Path) -> dict[str, Path]:
        return {
            p.relative_to(base).as_posix(): p
            for p in base.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(base).parts
        }

    current = relative_files(root)
    snapshot = relative_files(backup_dir)

    result = SnapshotDiff(
        created=sorted(set(current) - set(snapshot)),
        deleted=sorted(set(snapshot) - set(current)),
        modified=sorted(
            rel
            for rel in set(current) & set(snapshot)
            if current[rel].read_bytes() != snapshot[rel].read_bytes()
        ),
    )
    return result


def diff_snapshot(project: Project, snapshot: Snapshot) -> SnapshotDiff:
    """A preview of what restore_snapshot would change, for the
    confirmation prompt (see server.py's GET /sessions/{id}/snapshot/diff)
    - computed on demand rather than cached, since it has to reflect
    whatever the session has written up to the moment the user is about
    to confirm, not a stale snapshot-time view."""
    root = Path(project.folder_path).resolve()
    if snapshot.kind == "git":
        return _diff_git_snapshot(root, snapshot.location)
    return _diff_copy_snapshot(root, Path(snapshot.location))


def _discard_one(snapshot: Snapshot) -> None:
    """Cleans up whatever a single snapshot record points to (the git
    ref, or the backup copy) - the record itself is assumed already
    removed by the caller. Best-effort: if the project was since deleted
    or the git ref is already gone, there's nothing left to clean up
    beyond the record."""
    if snapshot.kind == "git":
        project = get_project(snapshot.project_id)
        if project is not None:
            root = Path(project.folder_path).resolve()
            if root.is_dir():
                _git(
                    ["update-ref", "-d", _snapshot_ref(snapshot.session_id, snapshot.turn_index)],
                    root,
                )
    else:
        shutil.rmtree(snapshot.location, ignore_errors=True)


def discard_snapshot(session_id: str) -> None:
    """Cleans up every restore point a session has (one per turn that
    wrote something - see storage/snapshots.py's list_snapshots), called
    when the session itself is deleted so none of them linger forever."""
    for snapshot in delete_snapshots_for_session(session_id):
        _discard_one(snapshot)


def discard_snapshots_for_project(project_id: str) -> int:
    """Same as discard_snapshot, scoped to every session's restore points
    for one project instead of one session's - called from server.py's
    DELETE /projects/{id}, before the Project record itself is removed
    (its folder_path is what a git-backed snapshot's ref cleanup needs -
    once the record's gone, get_project() can no longer resolve it).
    Without this, a project's snapshots become dead weight forever: they
    already can't be restored to (restore/diff both 404 once get_project()
    returns None for a deleted project), but nothing was removing the git
    ref or backup copy - see PLAN.md's "Purge des vieux snapshots" entry.
    Returns how many were removed, for the endpoint's own log."""
    removed = delete_snapshots_for_project(project_id)
    for snapshot in removed:
        _discard_one(snapshot)
    return len(removed)


# a session that's simply abandoned (never explicitly deleted) would
# otherwise keep its restore points - and the disk space and dangling git
# refs/backup copies they represent - forever. 30 days comfortably covers
# "I might still want to undo this" while still eventually reclaiming
# space for a conversation nobody's touched again.
SNAPSHOT_MAX_AGE_DAYS = 30


def purge_expired_snapshots(max_age_days: int = SNAPSHOT_MAX_AGE_DAYS) -> int:
    """Called once at harness startup (see server.py's lifespan): removes
    every snapshot older than max_age_days, regardless of whether its
    session or project still exist - the project-delete cascade
    (discard_snapshots_for_project) and session-delete cascade
    (discard_snapshot) only fire on those specific actions, so a
    conversation that's simply never revisited (project and session both
    still exist, nobody deleted anything) would otherwise accumulate
    restore points forever. Returns how many were removed, for the
    startup log."""
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    removed = delete_expired_snapshots(cutoff)
    for snapshot in removed:
        _discard_one(snapshot)
    return len(removed)
