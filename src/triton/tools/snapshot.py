"""Automatic safety net for the write tools (write_file/edit_file/
delete_file/move_file/git_commit): the first time one is about to run in
a given turn of a project-scoped session, that turn's starting state is
captured into a small homemade content-addressable store (see "Content
snapshots" below) - regardless of whether the project folder is itself a
git repo. One snapshot per (session, turn) - ensure_snapshot is a no-op
once a record exists for that specific turn_index, taken lazily on the
first write of the turn rather than eagerly, since most turns never write
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

Content snapshots (current format, used for every new snapshot): a plain
content-addressable blob store under snapshot_objects/<hash[:2]>/<hash>
(sha256 of a file's bytes, written once per unique content and shared by
every manifest that happens to reference it - identical files across
turns/sessions/projects cost storage exactly once) plus a small JSON
manifest per (session, turn) under snapshot_manifests/ mapping each
relative path to its blob's hash. Deliberately not backed by the
project's own git history even when it has one: a project meant to be
pushed to GitHub shouldn't have its safety net's internal bookkeeping
(dangling commits/refs) living in the same object database, and this
also means a non-git project gets the exact same space-efficient
treatment instead of the wasteful full `shutil.copytree` this used to do
for it. Restoring a blob prefers `cp -c` (APFS clonefile on macOS: a
copy-on-write clone, effectively free in time and disk space until
either side is later modified) and falls back to a plain copy elsewhere
- see _restore_blob.

Legacy snapshots ("git"/"copy" kind): the two formats used before content
snapshots existed - a dangling git commit for a git-repo project, or a
full recursive copy otherwise. No longer produced by ensure_snapshot, but
restore_snapshot/diff_snapshot/_discard_one still handle both so any
snapshot already on disk from before this change stays restorable until
it naturally expires (see purge_expired_snapshots). `git stash create`
looks like the obvious primitive for the git half, but it silently
ignores --include-untracked (verified against git 2.50), so a new file
the model was about to edit wouldn't have been covered - instead it built
the tree by hand in a scratch index (GIT_INDEX_FILE pointed at a
throwaway path): `git add -A` there stages tracked and untracked content
into *that* index only, never touching the repo's real index or working
tree, then `write-tree`/`commit-tree` turned it into a real (if
unreachable) commit object, anchored by a ref under
refs/triton/snapshots/<session_id>/<turn_index>."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

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
WRITE_TOOL_NAMES = {
    "write_file",
    "edit_file",
    "delete_file",
    "move_file",
    "git_commit",
    # switching branches (or creating one) changes the working tree's
    # actual file contents on disk, same as any other entry here -
    # git_push deliberately isn't: it only touches a remote, never the
    # local project state a snapshot exists to protect.
    "git_checkout",
}

BACKUP_ROOT = ROOT_DIR / "snapshot_backups"  # legacy "copy" kind only

# current format (see the module docstring's "Content snapshots" half):
# OBJECTS_ROOT holds the shared, content-addressed blobs; MANIFESTS_ROOT
# holds one small JSON file per (session, turn) mapping relative paths to
# blob hashes.
OBJECTS_ROOT = ROOT_DIR / "snapshot_objects"
MANIFESTS_ROOT = ROOT_DIR / "snapshot_manifests"

# Les dependances et artefacts sont regenerables, pas des fichiers source a
# versionner dans cet historique interne. Les exclure evite des diffs et des
# restaurations disproportionnes sur les projets JavaScript/Python.
IGNORED_DIRECTORY_NAMES = {
    ".git",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "venv",
}

# guards ensure_snapshot's read-then-write against two write tool calls
# landing at nearly the same moment - most plausibly two "code" subtasks
# in the same orchestrator run, writing to the same project from
# parallel threads (see agents/orchestrator.py's _run).
_LOCK = threading.Lock()


class RestoreError(Exception):
    pass


class InvalidSnapshotPathError(RestoreError):
    """A history-browser path did not resolve within its project folder."""


def validate_snapshot_relative_path(project: Project, rel_path: str) -> str:
    """Return a canonical relative path that stays inside the project.

    The history browser supplies this value as a query parameter. Resolving
    it first blocks traversal, absolute paths, and symlinks that point out of
    the project. ``strict=False`` keeps deleted snapshot files viewable.
    """
    root = Path(project.folder_path).resolve()
    raw_path = Path(rel_path)
    if raw_path.is_absolute():
        raise InvalidSnapshotPathError("snapshot file path must be relative to the project")

    resolved = (root / raw_path).resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as e:
        raise InvalidSnapshotPathError("snapshot file path resolves outside the project") from e

    if relative == Path("."):
        raise InvalidSnapshotPathError("snapshot file path must identify a file")
    return relative.as_posix()


def _git(
    args: list[str], cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    full_env = {**os.environ, **env} if env else None
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=15, env=full_env
    )


# --- legacy "git"/"copy" snapshot kinds -------------------------------
# No longer produced by ensure_snapshot (see the module docstring) - kept
# only so a snapshot already on disk from before the content store existed
# stays restorable via restore_snapshot/diff_snapshot/_discard_one until it
# naturally expires.


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


# --- content snapshots (current format) --------------------------------


def _project_files(root: Path) -> list[Path]:
    """Fichiers utiles du projet, sans dependances ni sorties de build.

    `Path.rglob` visite quand meme tous les fichiers exclus. Ici, les
    repertoires sont elagues pendant `os.walk`, ce qui evite de parcourir
    tout un node_modules a chaque clic dans l'historique.
    """
    files: list[Path] = []
    for directory, child_directories, child_files in os.walk(root):
        child_directories[:] = [
            name for name in child_directories if name not in IGNORED_DIRECTORY_NAMES
        ]
        directory_path = Path(directory)
        # Snapshots represent project-owned regular files. Following a
        # symlink here could otherwise copy arbitrary content from outside
        # the project into the internal history store.
        files.extend(
            path
            for name in child_files
            if not (path := directory_path / name).is_symlink() and path.is_file()
        )
    return files


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _blob_path(content_hash: str) -> Path:
    return OBJECTS_ROOT / content_hash[:2] / content_hash


def _store_blob(path: Path) -> str:
    """Adds `path`'s current content to the blob store if it isn't
    already there (same content, same hash, stored once - see the module
    docstring), and returns its hash either way. Written to a sibling
    temp file first and renamed into place, so a crash mid-copy never
    leaves a corrupt/truncated blob sitting under its final,
    content-addressed name (which _restore_blob and the GC pass both
    trust unconditionally)."""
    content_hash = _file_hash(path)
    blob_path = _blob_path(content_hash)
    if not blob_path.exists():
        blob_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = blob_path.with_name(f".{blob_path.name}.{uuid.uuid4().hex}.tmp")
        shutil.copyfile(path, tmp)
        tmp.replace(blob_path)
    return content_hash


def _restore_blob(content_hash: str, dest: Path) -> None:
    blob_path = _blob_path(content_hash)
    if not blob_path.is_file():
        raise RestoreError(f"snapshot blob missing: {content_hash}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "darwin":
        # APFS clonefile: a copy-on-write clone, effectively free in time
        # and disk space until either side is later modified - falls back
        # to a plain copy below if it fails (e.g. the blob store and the
        # project live on different volumes, where clonefile can't work).
        cloned = subprocess.run(
            ["cp", "-c", str(blob_path), str(dest)], capture_output=True, timeout=15
        )
        if cloned.returncode == 0:
            return
    shutil.copy2(blob_path, dest)


def _manifest_path(
    session_id: str, turn_index: int, state: Literal["before", "after"] = "before"
) -> Path:
    suffix = "" if state == "before" else ".after"
    return MANIFESTS_ROOT / session_id / f"{turn_index}{suffix}.json"


def _take_content_snapshot(
    root: Path,
    session_id: str,
    turn_index: int,
    state: Literal["before", "after"] = "before",
) -> str:
    """Hashes every file under `root` into the shared blob store, then
    writes a small JSON manifest (relative path -> blob hash) recording
    this turn's tree shape - see the module docstring's "Content
    snapshots" section. Returns the manifest's path, stored as the
    Snapshot record's `location`."""
    manifest = {p.relative_to(root).as_posix(): _store_blob(p) for p in _project_files(root)}
    manifest_file = _manifest_path(session_id, turn_index, state)
    manifest_file.parent.mkdir(parents=True, exist_ok=True)
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False))
    return str(manifest_file)


def _load_manifest(manifest_path: str) -> dict[str, str]:
    path = Path(manifest_path)
    if not path.is_file():
        raise RestoreError(f"snapshot manifest no longer exists: {manifest_path}")
    return json.loads(path.read_text())


def _restore_content_snapshot(root: Path, manifest_path: str) -> None:
    manifest = _load_manifest(manifest_path)

    # remove everything currently there (.git excepted) first, so a path
    # created after the snapshot doesn't survive the restore - the same
    # "checkout + clean" semantics as the legacy git backend.
    for entry in root.iterdir():
        if entry.name in IGNORED_DIRECTORY_NAMES:
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()

    for rel_path, content_hash in manifest.items():
        _restore_blob(content_hash, root / rel_path)


def _diff_content_snapshot(root: Path, manifest_path: str) -> "SnapshotDiff":
    manifest = _load_manifest(manifest_path)
    current = {p.relative_to(root).as_posix(): _file_hash(p) for p in _project_files(root)}

    return SnapshotDiff(
        created=sorted(set(current) - set(manifest)),
        deleted=sorted(set(manifest) - set(current)),
        modified=sorted(
            rel for rel in set(current) & set(manifest) if current[rel] != manifest[rel]
        ),
    )


def _diff_content_manifests(before_path: str, after_path: str) -> "SnapshotDiff":
    """Diff immuable entre les deux etats captures d'un meme tour."""
    before = _load_manifest(before_path)
    after = _load_manifest(after_path)
    return SnapshotDiff(
        created=sorted(set(after) - set(before)),
        deleted=sorted(set(before) - set(after)),
        modified=sorted(rel for rel in set(before) & set(after) if before[rel] != after[rel]),
    )


def ensure_snapshot(project: Project | None, session_id: str, turn_index: int) -> bool:
    """Takes a snapshot of the project folder if this turn hasn't had one
    yet (turn_index: the nth user message in this session, 1-based - see
    server.py's run_chat_stream), always into the content store (see the
    module docstring) regardless of whether the project is itself a git
    repo. Silently does nothing without a project, for a turn that
    already has a snapshot, or if the snapshot attempt itself fails (a
    permission error reading a file shouldn't block the write the model
    was actually trying to make - this is a best-effort safety net, not a
    precondition for writing). Returns whether a snapshot was actually
    just taken by this call - server.py's run_chat_stream uses this to
    surface a one-time "safety net is now active [for this turn]" notice
    in the conversation itself instead of only in the project file panel
    (see SnapshotSection.tsx), which required knowing the feature existed
    at all to go find it."""
    if project is None:
        return False

    with _LOCK:
        if get_snapshot(session_id, turn_index) is not None:
            return False

        root = Path(project.folder_path).resolve()
        if not root.is_dir():
            return False

        try:
            location = _take_content_snapshot(root, session_id, turn_index)
        except OSError:
            return False

        snapshot = Snapshot(
            session_id=session_id,
            project_id=project.id,
            kind="content",
            location=location,
            created_at=datetime.now(UTC).isoformat(),
            turn_index=turn_index,
        )
        save_snapshot(snapshot)
        return True


def finalize_snapshot(project: Project | None, session_id: str, turn_index: int) -> bool:
    """Scelle l'etat final d'un tour qui possede deja son point de depart.

    Un snapshot devient ainsi un vrai commit interne avant/apres, sans
    modifier le depot Git du projet. Le dernier etat ecrit remplace celui
    deja capture si un stream est termine une seconde fois apres reprise.
    """
    if project is None:
        return False

    with _LOCK:
        snapshot = get_snapshot(session_id, turn_index)
        if snapshot is None:
            return False
        root = Path(project.folder_path).resolve()
        if not root.is_dir():
            return False
        try:
            snapshot.after_location = _take_content_snapshot(root, session_id, turn_index, "after")
        except OSError:
            return False
        save_snapshot(snapshot)
        return True


def restore_snapshot(
    project: Project, snapshot: Snapshot, state: Literal["before", "after"] = "before"
) -> None:
    """Brings the project folder back to exactly the state ensure_snapshot
    captured. Only ever called from the explicit, user-confirmed restore
    endpoint (see server.py) - never automatically."""
    if state == "after" and snapshot.after_location is None:
        raise RestoreError("this restore point has no final state")
    location = snapshot.after_location if state == "after" else snapshot.location
    assert location is not None
    root = Path(project.folder_path).resolve()

    if snapshot.kind == "content":
        with _LOCK:
            _restore_content_snapshot(root, location)
    elif snapshot.kind == "git":
        # legacy - see the module docstring's "Legacy snapshots" section.
        checkout = _git(["checkout", location, "--", "."], root)
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
        # legacy "copy" - see the module docstring's "Legacy snapshots"
        # section.
        backup_dir = Path(location)
        if not backup_dir.is_dir():
            raise RestoreError(f"backup no longer exists: {backup_dir}")
        for entry in root.iterdir():
            if entry.name in IGNORED_DIRECTORY_NAMES:
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


# --- legacy "git"/"copy" diffing (see the module docstring) -----------


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
    if snapshot.kind == "content":
        return _diff_content_snapshot(root, snapshot.location)
    if snapshot.kind == "git":
        return _diff_git_snapshot(root, snapshot.location)
    return _diff_copy_snapshot(root, Path(snapshot.location))


def commit_diff_snapshot(snapshot: Snapshot) -> SnapshotDiff:
    """Les changements produits par un tour, entre ses deux etats figes."""
    if snapshot.kind != "content" or snapshot.after_location is None:
        raise RestoreError("this restore point has no immutable final state")
    return _diff_content_manifests(snapshot.location, snapshot.after_location)


def _content_from_manifest(manifest_path: str, rel_path: str) -> str | None:
    content_hash = _load_manifest(manifest_path).get(rel_path)
    if content_hash is None:
        return None
    blob_path = _blob_path(content_hash)
    if not blob_path.is_file():
        raise RestoreError(f"snapshot blob missing: {content_hash}")
    return blob_path.read_bytes().decode("utf-8", errors="replace")


def commit_snapshot_file_content(
    snapshot: Snapshot, rel_path: str
) -> tuple[str | None, str | None]:
    """Contenu avant/apres fige d'un fichier modifie par un tour."""
    if snapshot.kind != "content" or snapshot.after_location is None:
        raise RestoreError("this restore point has no immutable final state")
    return (
        _content_from_manifest(snapshot.location, rel_path),
        _content_from_manifest(snapshot.after_location, rel_path),
    )


def snapshot_file_content(
    project: Project, snapshot: Snapshot, rel_path: str
) -> tuple[str | None, str | None]:
    """(old, new) text content of `rel_path` for the restore-history
    browser's per-file diff (see server.py's GET .../snapshot/file):
    `old` as this snapshot captured it (None if the path didn't exist yet
    at snapshot time - it was created afterward), `new` as it currently
    is on disk (None if it no longer exists - deleted afterward, or
    never existed outside the snapshot). Both decoded permissively
    (invalid bytes replaced) since this is only ever rendered as text,
    never written back anywhere."""
    root = Path(project.folder_path).resolve()
    rel_path = validate_snapshot_relative_path(project, rel_path)
    new_path = root / rel_path
    new_content = (
        new_path.read_text(encoding="utf-8", errors="replace") if new_path.is_file() else None
    )

    if snapshot.kind == "content":
        manifest = _load_manifest(snapshot.location)
        content_hash = manifest.get(rel_path)
        if content_hash is None:
            return None, new_content
        blob_path = _blob_path(content_hash)
        if not blob_path.is_file():
            raise RestoreError(f"snapshot blob missing: {content_hash}")
        old_content = blob_path.read_bytes().decode("utf-8", errors="replace")
        return old_content, new_content

    if snapshot.kind == "git":
        result = _git(["show", f"{snapshot.location}:{rel_path}"], root)
        old_content = result.stdout if result.returncode == 0 else None
        return old_content, new_content

    backup_target = Path(snapshot.location) / rel_path
    old_content = (
        backup_target.read_text(encoding="utf-8", errors="replace")
        if backup_target.is_file()
        else None
    )
    return old_content, new_content


def _discard_one(snapshot: Snapshot) -> None:
    """Cleans up whatever a single snapshot record points to (the
    manifest file, the legacy git ref, or the legacy backup copy) - the
    record itself is assumed already removed by the caller. Best-effort:
    if the project was since deleted or the git ref is already gone,
    there's nothing left to clean up beyond the record. A content
    snapshot's blobs are deliberately NOT touched here - they may be
    shared by other manifests still alive, see _gc_unreferenced_blobs for
    the actual reclaim step."""
    if snapshot.kind == "content":
        Path(snapshot.location).unlink(missing_ok=True)
        if snapshot.after_location is not None:
            Path(snapshot.after_location).unlink(missing_ok=True)
    elif snapshot.kind == "git":
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


def _referenced_blob_hashes() -> set[str]:
    hashes: set[str] = set()
    if not MANIFESTS_ROOT.is_dir():
        return hashes
    for manifest_file in MANIFESTS_ROOT.rglob("*.json"):
        try:
            manifest = json.loads(manifest_file.read_text())
        except (OSError, ValueError):
            continue
        hashes.update(manifest.values())
    return hashes


def _gc_unreferenced_blobs() -> int:
    """Removes every blob no remaining manifest points to - content
    snapshots' counterpart to git's own gc (see the module docstring): a
    blob may be shared by several manifests (that's the whole point of
    content-addressing it), so a manifest being deleted doesn't mean its
    blobs can go too, only whichever ones nothing references anymore
    once it's gone. Meant to be called once after a batch of manifests
    was just removed (discard_snapshot/discard_snapshots_for_project/
    purge_expired_snapshots), not per snapshot, since it walks every
    remaining manifest to build the referenced set. Returns how many
    blobs were removed, for the caller's own log."""
    if not OBJECTS_ROOT.is_dir():
        return 0
    referenced = _referenced_blob_hashes()
    removed = 0
    for blob_path in OBJECTS_ROOT.glob("*/*"):
        if blob_path.name not in referenced:
            blob_path.unlink(missing_ok=True)
            removed += 1
    return removed


def discard_snapshot(session_id: str) -> None:
    """Cleans up every restore point a session has (one per turn that
    wrote something - see storage/snapshots.py's list_snapshots), called
    when the session itself is deleted so none of them linger forever."""
    with _LOCK:
        for snapshot in delete_snapshots_for_session(session_id):
            _discard_one(snapshot)
        _gc_unreferenced_blobs()


def discard_snapshots_for_project(project_id: str) -> int:
    """Same as discard_snapshot, scoped to every session's restore points
    for one project instead of one session's - called from server.py's
    DELETE /projects/{id}, before the Project record itself is removed
    (its folder_path is what a legacy git-backed snapshot's ref cleanup
    needs - once the record's gone, get_project() can no longer resolve
    it). Without this, a project's snapshots become dead weight forever:
    they already can't be restored to (restore/diff both 404 once
    get_project() returns None for a deleted project), but nothing was
    removing the manifest/git ref/backup copy - see PLAN.md's "Purge des
    vieux snapshots" entry. Returns how many were removed, for the
    endpoint's own log."""
    with _LOCK:
        removed = delete_snapshots_for_project(project_id)
        for snapshot in removed:
            _discard_one(snapshot)
        _gc_unreferenced_blobs()
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
    with _LOCK:
        removed = delete_expired_snapshots(cutoff)
        for snapshot in removed:
            _discard_one(snapshot)
        _gc_unreferenced_blobs()
    return len(removed)
