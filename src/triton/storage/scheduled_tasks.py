"""Recurring prompts (PLAN.md's "Tâches récurrentes (façon cron)" entry):
each task resends its own prompt text into its own dedicated session on a
schedule (hourly/daily/weekly), checked only while the backend happens to
be running - see server.py's poll loop, started from lifespan. No OS-level
cron, no guarantee of firing at the exact moment, and deliberately no
catch-up: due_tasks() only cares whether next_run has passed "by now",
never how many intervals it's been overdue by, and mark_fired() always
recomputes the next occurrence from the current moment - a task whose app
was closed for 3 days fires once, not three times, next time it's checked."""

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from triton.paths import ROOT_DIR

SCHEDULED_TASKS_FILE = ROOT_DIR / "scheduled_tasks.json"

Frequency = Literal["hourly", "daily", "weekly"]


@dataclass
class ScheduledTask:
    id: str
    prompt: str
    frequency: Frequency
    # "HH:MM", 24h - the time of day it fires for daily/weekly. Only the
    # minute part matters for hourly (fires at that minute of every hour).
    time_of_day: str
    project_id: str
    # dedicated session this task's prompt is sent into every time it
    # fires (created once, alongside the task itself - see server.py's
    # POST /scheduled_tasks) so its history accumulates across runs like
    # an ordinary conversation, instead of starting from scratch each time.
    session_id: str
    # 0=Monday..6=Sunday - required (and only meaningful) for "weekly"
    day_of_week: int | None = None
    enabled: bool = True
    next_run: str = ""
    last_run: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


def compute_next_run(
    frequency: Frequency, time_of_day: str, day_of_week: int | None, from_time: datetime
) -> datetime:
    """The next occurrence strictly after `from_time` - always computed
    from "now" (whenever this is called), never from a task's own
    possibly-long-overdue next_run, which is exactly what keeps a missed
    occurrence from ever being caught up on: there's nothing to catch up,
    the next one is just whatever comes after the moment this runs."""
    hour, minute = (int(p) for p in time_of_day.split(":"))
    if frequency == "hourly":
        candidate = from_time.replace(minute=minute, second=0, microsecond=0)
        if candidate <= from_time:
            candidate += timedelta(hours=1)
        return candidate
    if frequency == "daily":
        candidate = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= from_time:
            candidate += timedelta(days=1)
        return candidate
    if day_of_week is None:
        raise ValueError("day_of_week is required for a weekly task")
    candidate = from_time.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate += timedelta(days=(day_of_week - candidate.weekday()) % 7)
    if candidate <= from_time:
        candidate += timedelta(days=7)
    return candidate


def load_tasks() -> list[ScheduledTask]:
    if not SCHEDULED_TASKS_FILE.exists():
        return []
    try:
        raw = json.loads(SCHEDULED_TASKS_FILE.read_text())
    except (OSError, ValueError):
        # a partially-written file (crash mid-write) shouldn't take down
        # every other task, or the poll loop that reads this every minute
        return []
    return [ScheduledTask(**t) for t in raw]


def _save_all(tasks: list[ScheduledTask]) -> None:
    SCHEDULED_TASKS_FILE.write_text(
        json.dumps([asdict(t) for t in tasks], ensure_ascii=False, indent=2)
    )


def create_task(
    prompt: str,
    frequency: Frequency,
    time_of_day: str,
    project_id: str,
    session_id: str,
    day_of_week: int | None = None,
) -> ScheduledTask:
    now = datetime.now(UTC)
    task = ScheduledTask(
        id=uuid.uuid4().hex,
        prompt=prompt,
        frequency=frequency,
        time_of_day=time_of_day,
        day_of_week=day_of_week,
        project_id=project_id,
        session_id=session_id,
        next_run=compute_next_run(frequency, time_of_day, day_of_week, now).isoformat(),
    )
    tasks = load_tasks()
    tasks.append(task)
    _save_all(tasks)
    return task


def delete_task(task_id: str) -> bool:
    tasks = load_tasks()
    remaining = [t for t in tasks if t.id != task_id]
    if len(remaining) == len(tasks):
        return False
    _save_all(remaining)
    return True


def set_enabled(task_id: str, enabled: bool) -> ScheduledTask | None:
    tasks = load_tasks()
    for t in tasks:
        if t.id == task_id:
            t.enabled = enabled
            _save_all(tasks)
            return t
    return None


def due_tasks(now: datetime) -> list[ScheduledTask]:
    return [t for t in load_tasks() if t.enabled and datetime.fromisoformat(t.next_run) <= now]


def mark_fired(task_id: str, fired_at: datetime) -> ScheduledTask | None:
    """Advances next_run BEFORE the task's prompt actually runs (see
    server.py's poll loop) - not after - so a task whose run raises/hangs
    still moves on to its next occurrence instead of being retried every
    poll interval indefinitely."""
    tasks = load_tasks()
    for t in tasks:
        if t.id == task_id:
            t.last_run = fired_at.isoformat()
            t.next_run = compute_next_run(
                t.frequency, t.time_of_day, t.day_of_week, fired_at
            ).isoformat()
            _save_all(tasks)
            return t
    return None
