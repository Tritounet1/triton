from pathlib import Path

# repo root, regardless of where the triton package itself is installed/run
# from - keeps runtime data (sessions/, logs/, background_tasks_state/, ...)
# living at the repo root, matching where main.py/server.py are launched
# from and where .gitignore expects them.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
