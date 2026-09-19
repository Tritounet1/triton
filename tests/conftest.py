"""Project-wide test fixtures. Deliberately the only thing here - every
other test file still isolates its own storage directly (projects.json,
sessions/, ...), see their own `_isolated_storage` fixtures. This one
autouse fixture is the exception: log_event (storage/logs.py) fires
unconditionally on every tool_call/model_call that flows through
run_chat_stream, including from a test that only means to fake the
*model* response - a monkeypatched timed_stream_chat still drives the
real tool-execution/logging code around it. Missing this in even one
test file leaks real lines into the user's own logs/events.jsonl.

Found via exactly that: a real ~12k-line log file, a third of it
test-generated tool_call spam (pytest tmp-dir paths as the giveaway),
pushing GET /logs' 500-line window past the user's actual history and
corrupting the desktop app's own cost dashboard. test_yolo_mode.py's
write-tool test was one confirmed source; likely not the only one, given
how easy this is to miss per file (test_session_model_and_cost.py's own
isolation fixture, written for exactly this concern, only patched
server.py's copy of LOGS_FILE and missed storage/logs.py's own - see the
comment below for why both need it)."""

import pytest

import server
from triton import mcp_client
from triton.storage import logs, settings


@pytest.fixture(autouse=True)
def _isolate_logs(tmp_path, monkeypatch):
    logs_file = tmp_path / "events.jsonl"
    monkeypatch.setattr(logs, "LOGS_FILE", logs_file)
    # server.py does `from triton.storage.logs import LOGS_FILE` directly -
    # its own separate name bound at import time (GET /logs reads that
    # copy, not storage/logs.py's) - both need patching, same footgun
    # documented in test_budget_enforcement.py/test_session_model_and_cost.py.
    monkeypatch.setattr(server, "LOGS_FILE", logs_file)


@pytest.fixture(autouse=True)
def _isolate_keychain(monkeypatch):
    """Tests must never create/overwrite credentials in the user's Keychain."""
    secrets: dict[str, str] = {}

    def get_secret(account: str) -> str | None:
        return secrets.get(account)

    def set_secret(account: str, value: str | None) -> None:
        if value is None:
            secrets.pop(account, None)
        else:
            secrets[account] = value

    monkeypatch.setattr(settings, "get_secret", get_secret)
    monkeypatch.setattr(settings, "set_secret", set_secret)
    monkeypatch.setattr(mcp_client, "get_secret", get_secret)
    monkeypatch.setattr(mcp_client, "set_secret", set_secret)
