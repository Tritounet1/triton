"""Persisted records for the write-tool safety net (see
triton/tools/snapshot.py for the actual git/copy snapshot logic): which
session has already had its project folder snapshotted, and where that
snapshot lives. One record per session_id - stored the same way as
projects.json/sessions so it survives a harness restart, which matters
here since the record is also what makes ensure_snapshot idempotent
(without it, a restart mid-session would snapshot again on the next
write, silently discarding the original "before this session" state)."""

import json
from dataclasses import asdict, dataclass
from typing import Literal

from triton.paths import ROOT_DIR

SNAPSHOTS_FILE = ROOT_DIR / "snapshots.json"

SnapshotKind = Literal["git", "copy"]


@dataclass
class Snapshot:
    session_id: str
    project_id: str
    kind: SnapshotKind
    # git: the sha of the dangling commit the state was captured into.
    # copy: the backup directory's absolute path.
    location: str
    created_at: str


def _load() -> dict[str, Snapshot]:
    if not SNAPSHOTS_FILE.exists():
        return {}
    raw = json.loads(SNAPSHOTS_FILE.read_text())
    return {session_id: Snapshot(**data) for session_id, data in raw.items()}


def _save(snapshots: dict[str, Snapshot]) -> None:
    SNAPSHOTS_FILE.write_text(
        json.dumps(
            {session_id: asdict(s) for session_id, s in snapshots.items()},
            ensure_ascii=False,
            indent=2,
        )
    )


def get_snapshot(session_id: str) -> Snapshot | None:
    return _load().get(session_id)


def save_snapshot(snapshot: Snapshot) -> None:
    snapshots = _load()
    snapshots[snapshot.session_id] = snapshot
    _save(snapshots)


def delete_snapshot(session_id: str) -> Snapshot | None:
    """Removes the record and returns it (or None if there wasn't one), so
    the caller can also clean up the underlying git ref/backup directory
    it pointed to - see triton/tools/snapshot.py's discard_snapshot."""
    snapshots = _load()
    snapshot = snapshots.pop(session_id, None)
    if snapshot is not None:
        _save(snapshots)
    return snapshot
