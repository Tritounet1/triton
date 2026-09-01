"""Persists in-flight orchestrator runs to disk (one JSON file per run,
orchestrator_runs/<id>.json) so a harness restart doesn't silently lose
one - see agents/orchestrator.py's resume_incomplete_runs(), called once
at startup (server.py's lifespan). Deliberately dumb here: this module
only reads/writes plain JSON-safe dicts, the dataclass<->dict conversion
lives in orchestrator.py itself (OrchestratorRun/Subtask are defined
there, and this module can't import them back without a circular
import - storage/ is a dependency of agents/, not the other way around).

A run reaching a terminal state (done/error) has its file removed right
after being folded into its conversation's session - from then on the
session is the only copy that matters, same as the in-memory RUNS dict
already worked before this existed (see orchestrator.py's own module
docstring)."""

import json
from pathlib import Path

from triton.paths import ROOT_DIR

ORCHESTRATOR_RUNS_DIR = ROOT_DIR / "orchestrator_runs"


def run_path(run_id: str) -> Path:
    return ORCHESTRATOR_RUNS_DIR / f"{run_id}.json"


def save_run(run_id: str, data: dict[str, object]) -> None:
    ORCHESTRATOR_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_path(run_id).write_text(json.dumps(data, ensure_ascii=False, indent=2))


def delete_run(run_id: str) -> None:
    run_path(run_id).unlink(missing_ok=True)


def load_all_runs() -> list[dict[str, object]]:
    """Every persisted run, most recently created first isn't guaranteed
    (filename order = run id, not creation time) - callers that care about
    order should sort by the run's own created_at field."""
    if not ORCHESTRATOR_RUNS_DIR.exists():
        return []
    runs: list[dict[str, object]] = []
    for path in sorted(ORCHESTRATOR_RUNS_DIR.glob("*.json")):
        try:
            runs.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            # a partially-written file (crash mid-write) shouldn't take
            # down startup for every other run - skip it
            continue
    return runs
