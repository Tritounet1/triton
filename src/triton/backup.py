"""Full data backup/export - GET /backup/export in server.py. Zips every
file/directory this app writes under ROOT_DIR (sessions, projects,
memory, snapshots, MCP server configs, settings...), for migrating to a
new machine or as a safety net before a risky manual change - the
write-tool safety net (tools/snapshot.py) only covers project folders,
nothing about the harness's own state.

Includes the app state stored under ROOT_DIR. OpenRouter/Tavily keys and
MCP secrets live in the macOS Keychain and are therefore deliberately not
exported. A legacy `.env` file can still contain credentials and is included
as-is; keep the resulting archive as securely as that file."""

import io
import zipfile
from pathlib import Path

from triton.paths import ROOT_DIR

# Every top-level file/directory this app writes under ROOT_DIR - see
# each storage/tools module's own ROOT_DIR / "..." constant. Listed here
# by name rather than importing each module's constant: importing every
# storage/tools module just for its path would pull in their own
# dependencies for no reason, and this list is the actual contract for
# "what counts as the app's data", independent of which module happens
# to own a given path today.
BACKUP_FILES = [
    "projects.json",
    "settings.json",
    "mcp_servers.json",
    "snapshots.json",
    "scheduled_tasks.json",
    "memory_global.md",
    ".env",
]
BACKUP_DIRS = [
    "sessions",
    "project_memory",
    "logs",
    "background_tasks_state",
    "orchestrator_runs",
    "snapshot_objects",
    "snapshot_manifests",
    "snapshot_backups",
]


def build_backup_zip() -> bytes:
    """A zip archive (in memory) of everything currently in BACKUP_FILES/
    BACKUP_DIRS - best-effort, like every other backup-adjacent code path
    in this app (see snapshot.py's own docstrings): a file/directory that
    doesn't exist yet (a feature never used, a fresh install) is simply
    skipped rather than raising, since "nothing to include" isn't an
    error. Paths are stored relative to ROOT_DIR, so restoring is just
    unzipping into a fresh ROOT_DIR."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in BACKUP_FILES:
            path = ROOT_DIR / name
            if path.is_file():
                zf.write(path, arcname=name)
        for name in BACKUP_DIRS:
            root = ROOT_DIR / name
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=str(Path(name) / path.relative_to(root)))
    return buffer.getvalue()
