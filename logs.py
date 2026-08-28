import datetime
import json
from pathlib import Path

LOGS_DIR = Path(__file__).parent / "logs"
LOGS_FILE = LOGS_DIR / "events.jsonl"


def log_event(**fields: object) -> None:
    """Appends a JSON line to the log file (timestamp + free-form fields)."""
    LOGS_DIR.mkdir(exist_ok=True)
    event = {
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        **fields,
    }
    with LOGS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
