"""Persisted records for the write-tool safety net (see
triton/tools/snapshot.py for the actual git/copy snapshot logic): one
record per (session, turn) that actually had a write happen, storing
where that snapshot lives - stored the same way as projects.json/sessions
so it survives a harness restart, which matters here since the record is
also what makes ensure_snapshot idempotent per turn (without it, a
restart mid-turn would snapshot again on the next write in that same
turn, silently discarding the real "before this turn" state).

Multiple records can share a session_id (one per turn whose first write
triggered a snapshot - a turn with no writes has none) - this is what
lets a restore target "undo the last turn" as well as "undo everything",
rather than only the latter. All-flat-list rather than keyed by
session_id: a lookup by (session_id, turn_index) is no more expensive
than a dict lookup would have been at this scale (a handful of snapshots
per session, purged well before the file could grow large - see
tools/snapshot.py's purge_expired_snapshots), and every other query this
module needs (every snapshot for a session, every one for a project) is
naturally a filter over the same flat list."""

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
    # which turn (the nth user message in this session, 1-based) this
    # snapshot precedes - see tools/snapshot.py's ensure_snapshot.
    turn_index: int


def _load() -> list[Snapshot]:
    if not SNAPSHOTS_FILE.exists():
        return []
    raw = json.loads(SNAPSHOTS_FILE.read_text())
    if isinstance(raw, dict):
        # pre-turn-tracking format: {session_id: record}, one snapshot per
        # session covering its whole history - equivalent to turn_index=1
        # under the current model. Migrated in place on first read after
        # upgrading (re-saved in the new list format immediately below),
        # so this branch only ever runs once per real snapshots.json.
        migrated = [Snapshot(turn_index=1, **data) for data in raw.values()]
        _save(migrated)
        return migrated
    return [Snapshot(**data) for data in raw]


def _save(snapshots: list[Snapshot]) -> None:
    SNAPSHOTS_FILE.write_text(
        json.dumps([asdict(s) for s in snapshots], ensure_ascii=False, indent=2)
    )


def list_snapshots(session_id: str) -> list[Snapshot]:
    """Every restore point for a session, oldest turn first."""
    return sorted(
        (s for s in _load() if s.session_id == session_id),
        key=lambda s: s.turn_index,
    )


def get_snapshot(session_id: str, turn_index: int) -> Snapshot | None:
    return next(
        (s for s in _load() if s.session_id == session_id and s.turn_index == turn_index),
        None,
    )


def save_snapshot(snapshot: Snapshot) -> None:
    snapshots = [
        s
        for s in _load()
        if not (s.session_id == snapshot.session_id and s.turn_index == snapshot.turn_index)
    ]
    snapshots.append(snapshot)
    _save(snapshots)


def delete_snapshots_for_session(session_id: str) -> list[Snapshot]:
    """Removes every restore point for a session and returns them, so the
    caller can also clean up what each one points to (the git ref, or the
    backup copy) - see tools/snapshot.py's discard_snapshot."""
    snapshots = _load()
    removed = [s for s in snapshots if s.session_id == session_id]
    if removed:
        _save([s for s in snapshots if s.session_id != session_id])
    return removed


def delete_snapshots_for_project(project_id: str) -> list[Snapshot]:
    """Same as delete_snapshots_for_session, scoped to a project instead -
    every session that ever wrote to it may have its own restore points,
    all now unreachable once the project itself is gone (get_project()
    returns None, which restore/diff already treat as a 404) - see
    tools/snapshot.py's discard_snapshots_for_project."""
    snapshots = _load()
    removed = [s for s in snapshots if s.project_id == project_id]
    if removed:
        _save([s for s in snapshots if s.project_id != project_id])
    return removed


def delete_expired_snapshots(cutoff_iso: str) -> list[Snapshot]:
    """Every snapshot older than cutoff_iso (an ISO-8601 UTC timestamp,
    directly comparable to created_at as plain strings since both are
    always datetime.now(UTC).isoformat()) - see tools/snapshot.py's
    purge_expired_snapshots."""
    snapshots = _load()
    removed = [s for s in snapshots if s.created_at < cutoff_iso]
    if removed:
        _save([s for s in snapshots if s.created_at >= cutoff_iso])
    return removed
