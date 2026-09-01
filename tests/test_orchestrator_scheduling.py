"""_schedule_waves groups an orchestrator run's subtasks into
dependency-respecting waves (Kahn's algorithm - see orchestrator.py's
module docstring): every subtask in a wave depends only on subtasks in
earlier waves, so it's safe to run a whole wave's threads in parallel like
the old fully-independent behavior did for every subtask at once."""

from triton.agents.orchestrator import Subtask, _schedule_waves


def _subtask(id_: str, depends_on: list[str] | None = None) -> Subtask:
    return Subtask(id=id_, role="research", description="d", model="m", depends_on=depends_on or [])


def test_no_dependencies_is_a_single_wave():
    subtasks = [_subtask("a"), _subtask("b"), _subtask("c")]
    waves = _schedule_waves(subtasks)
    assert len(waves) == 1
    assert {s.id for s in waves[0]} == {"a", "b", "c"}


def test_a_dependent_subtask_waits_for_its_own_wave():
    a = _subtask("a")
    b = _subtask("b", depends_on=["a"])
    waves = _schedule_waves([a, b])
    assert [{s.id for s in w} for w in waves] == [{"a"}, {"b"}]


def test_independent_subtasks_still_run_together_alongside_a_chain():
    a = _subtask("a")
    b = _subtask("b", depends_on=["a"])
    c = _subtask("c")
    waves = _schedule_waves([a, b, c])
    assert [{s.id for s in w} for w in waves] == [{"a", "c"}, {"b"}]


def test_a_diamond_dependency_resolves_in_three_waves():
    a = _subtask("a")
    b = _subtask("b", depends_on=["a"])
    c = _subtask("c", depends_on=["a"])
    d = _subtask("d", depends_on=["b", "c"])
    waves = _schedule_waves([a, b, c, d])
    assert [{s.id for s in w} for w in waves] == [{"a"}, {"b", "c"}, {"d"}]


def test_a_dependency_id_missing_from_the_run_is_ignored():
    a = _subtask("a", depends_on=["does-not-exist"])
    waves = _schedule_waves([a])
    assert waves == [[a]]


def test_cycle_falls_back_to_one_wave_instead_of_deadlocking():
    a = _subtask("a", depends_on=["b"])
    b = _subtask("b", depends_on=["a"])
    waves = _schedule_waves([a, b])
    assert len(waves) == 1
    assert {s.id for s in waves[0]} == {"a", "b"}
