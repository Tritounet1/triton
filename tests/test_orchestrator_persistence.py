"""Orchestrator runs are mirrored to disk (storage/orchestrator_runs.py)
so resume_incomplete_runs() (called once at harness startup - see
server.py's lifespan) can pick a crashed run back up instead of losing it
silently, the way an in-memory-only RUNS dict used to. Every test here
runs _resume_one's background thread synchronously (see _SyncThread) so
assertions can run right after resume_incomplete_runs() returns, without
a real race against a spawned thread."""

import pytest

from triton.agents import orchestrator
from triton.storage import orchestrator_runs as storage


class _SyncThread:
    """Stand-in for threading.Thread that runs its target immediately on
    start() instead of on a background thread - makes resume's real
    background dispatch deterministic to assert on."""

    def __init__(self, target, args=(), daemon=None):
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)

    def join(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, "ORCHESTRATOR_RUNS_DIR", tmp_path / "orchestrator_runs")
    monkeypatch.setattr(orchestrator, "RUNS", {})
    monkeypatch.setattr(orchestrator.threading, "Thread", _SyncThread)


def _done_subtask(id_: str) -> orchestrator.Subtask:
    return orchestrator.Subtask(
        id=id_,
        role="research",
        description="d",
        model="m",
        status="done",
        result="ok",
        tool_calls=[
            orchestrator.SubtaskToolCall(tool="web_search", args={"query": "x"}, result="r")
        ],
    )


def test_run_to_dict_and_back_round_trips():
    run = orchestrator.OrchestratorRun(
        id="r1",
        task="do x",
        status="running",
        project_id="p1",
        session_id="s1",
        subtasks=[_done_subtask("s1a")],
    )
    restored = orchestrator._run_from_dict(orchestrator._run_to_dict(run))
    assert restored == run


def test_resume_drops_a_stale_file_for_an_already_terminal_run():
    run = orchestrator.OrchestratorRun(id="r1", task="t", status="done", final_result="x")
    storage.save_run(run.id, orchestrator._run_to_dict(run))

    resumed = orchestrator.resume_incomplete_runs()

    assert resumed == []
    assert storage.load_all_runs() == []


def test_resume_reruns_only_unfinished_subtasks_and_keeps_finished_results(monkeypatch):
    done = _done_subtask("done-one")
    unfinished = orchestrator.Subtask(id="unfinished", role="research", description="d", model="m")
    run = orchestrator.OrchestratorRun(
        id="r2", task="t", status="running", subtasks=[done, unfinished]
    )
    storage.save_run(run.id, orchestrator._run_to_dict(run))

    seen_unfinished_ids: list[list[str]] = []

    def _fake_execute(
        run_arg: orchestrator.OrchestratorRun,
        _project: None,
        _roles: list[orchestrator.MultiAgentRole],
    ) -> None:
        seen_unfinished_ids.append([s.id for s in run_arg.subtasks if s.status != "done"])
        run_arg.status = "done"
        run_arg.final_result = "resumed"

    monkeypatch.setattr(orchestrator, "_execute_subtasks", _fake_execute)

    resumed = orchestrator.resume_incomplete_runs()

    assert resumed == ["r2"]
    assert seen_unfinished_ids == [["unfinished"]]
    assert orchestrator.RUNS["r2"].subtasks[0].result == "ok"


def test_resume_of_a_run_that_never_got_past_planning_restarts_from_scratch(monkeypatch):
    run = orchestrator.OrchestratorRun(id="r3", task="t", status="planning", subtasks=[])
    storage.save_run(run.id, orchestrator._run_to_dict(run))

    replanned: list[str] = []
    monkeypatch.setattr(orchestrator, "_run", lambda run_arg: replanned.append(run_arg.id))

    resumed = orchestrator.resume_incomplete_runs()

    assert resumed == ["r3"]
    assert replanned == ["r3"]
