import datetime
import json

from triton.paths import ROOT_DIR

LOGS_DIR = ROOT_DIR / "logs"
LOGS_FILE = LOGS_DIR / "events.jsonl"


def log_event(**fields: object) -> None:
    """Appends a JSON line to the log file (timestamp + free-form fields)."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    event = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        **fields,
    }
    with LOGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def events_for_month(month_key: str | None = None) -> list[dict[str, object]]:
    """Every logged event for one calendar month ('YYYY-MM', current month
    by default), regardless of `type` - the full, unfiltered scan
    current_month_cost() already did internally, now reusable directly by
    a caller that needs more than just the summed total (see server.py's
    GET /logs/cost_summary)."""
    if not LOGS_FILE.exists():
        return []
    key = month_key or datetime.datetime.now().strftime("%Y-%m")
    events: list[dict[str, object]] = []
    for line in LOGS_FILE.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if str(event.get("timestamp", "")).startswith(key):
            events.append(event)
    return events


def current_month_cost() -> float:
    """Sums cost_usd across every logged event for the current calendar
    month, regardless of its `type` - a model_call, an orchestrator
    planning/synthesis call, a subagent call, whatever's logged with a
    cost_usd field counts, so a new cost-generating code path is covered
    automatically as long as it logs that field too. Backs the monthly
    budget check in server.py (see storage/settings.py's
    load_monthly_budget/save_monthly_budget for the budget value itself)."""
    total = 0.0
    for event in events_for_month():
        cost = event.get("cost_usd")
        if isinstance(cost, int | float):
            total += cost
    return total
