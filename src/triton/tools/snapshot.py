"""Automatic safety net for the write tools (write_file/edit_file/
delete_file/move_file/git_commit): the first time one of them is about to
run in a project-scoped session, the project folder's current state is
captured -
a dangling git commit if the folder is a git repo, or a plain recursive
copy otherwise (see the module docstring's two halves below) - so the
whole session's writes can be undone in one action later via
restore_snapshot(), no matter how many individual edits happened along
the way. One snapshot per session (ensure_snapshot is a no-op once a
record exists for that session_id), taken lazily on the first write
rather than eagerly when a project is opened, since most sessions never
write anything.

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
real (if unreachable) commit object. A ref under refs/triton/snapshots/
keeps that commit from being garbage-collected."""

import os
import shutil
import subprocess
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

from triton.paths import ROOT_DIR
from triton.storage.projects import Project, get_project
from triton.storage.snapshots import Snapshot, delete_snapshot, get_snapshot, save_snapshot

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


def _take_git_snapshot(root: Path, session_id: str) -> str | None:
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

        ref = _git(["update-ref", f"refs/triton/snapshots/{session_id}", commit_sha], root)
        if ref.returncode != 0:
            return None
        return commit_sha
    finally:
        scratch_index.unlink(missing_ok=True)


def _take_copy_snapshot(root: Path, session_id: str) -> str:
    backup_dir = BACKUP_ROOT / session_id
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root, backup_dir, ignore=shutil.ignore_patterns(".git"))
    return str(backup_dir)


def ensure_snapshot(project: Project | None, session_id: str) -> None:
    """Takes a snapshot of the project folder if this session hasn't had
    one yet. Silently does nothing without a project, for a session that
    already has a snapshot, or if the snapshot attempt itself fails (a
    missing/broken git binary shouldn't block the write the model was
    actually trying to make - this is a best-effort safety net, not a
    precondition for writing)."""
    if project is None:
        return

    with _LOCK:
        if get_snapshot(session_id) is not None:
            return

        root = Path(project.folder_path).resolve()
        if not root.is_dir():
            return

        try:
            if _is_git_repo(root):
                sha = _take_git_snapshot(root, session_id)
                if sha is None:
                    return
                snapshot = Snapshot(
                    session_id=session_id,
                    project_id=project.id,
                    kind="git",
                    location=sha,
                    created_at=datetime.now(UTC).isoformat(),
                )
            else:
                location = _take_copy_snapshot(root, session_id)
                snapshot = Snapshot(
                    session_id=session_id,
                    project_id=project.id,
                    kind="copy",
                    location=location,
                    created_at=datetime.now(UTC).isoformat(),
                )
        except OSError:
            return

        save_snapshot(snapshot)


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


def discard_snapshot(session_id: str) -> None:
    """Cleans up a session's snapshot record and whatever it points to
    (the git ref, or the backup copy) - called when the session itself is
    deleted, so neither lingers forever. Best-effort: if the project was
    since deleted or the git ref is already gone, there's nothing left to
    clean up beyond the record itself."""
    snapshot = delete_snapshot(session_id)
    if snapshot is None:
        return

    if snapshot.kind == "git":
        project = get_project(snapshot.project_id)
        if project is not None:
            root = Path(project.folder_path).resolve()
            if root.is_dir():
                _git(["update-ref", "-d", f"refs/triton/snapshots/{session_id}"], root)
    else:
        shutil.rmtree(snapshot.location, ignore_errors=True)
