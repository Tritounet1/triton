import sys
from pathlib import Path

from platformdirs import user_data_dir


def _compute_root_dir() -> Path:
    # PyInstaller sets sys.frozen; server.py then runs from a temp
    # extraction dir (or next to a onedir build) that has nothing to do
    # with "the repo" and isn't guaranteed writable/stable across runs -
    # use the OS's standard per-user app data directory instead, so
    # sessions/logs/settings survive updates and reinstalls.
    if getattr(sys, "frozen", False):
        return Path(user_data_dir("Triton", "tritonet"))
    # dev mode: repo root, regardless of where the triton package itself is
    # installed/run from - keeps runtime data (sessions/, logs/,
    # background_tasks_state/, ...) living at the repo root, matching where
    # main.py/server.py are launched from and where .gitignore expects them.
    return Path(__file__).resolve().parent.parent.parent


ROOT_DIR = _compute_root_dir()
# every other module in this package assumes ROOT_DIR itself already
# exists when creating a subdirectory (mkdir(exist_ok=True), no
# parents=True) or writing a file directly under it (settings.json,
# projects.json, ...) - true in dev mode (it's the repo root) but not for
# a frozen build's fresh per-user app data dir on a first launch, where
# nothing has created it yet. Guaranteeing it here once covers every
# consumer instead of patching each call site's assumption individually.
ROOT_DIR.mkdir(parents=True, exist_ok=True)
