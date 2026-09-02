"""run_chat_stream used to have no try/except around the model call at
all: once llm/api.py's own retry budget (_with_retry) was exhausted, or
for a non-transient failure (bad model name, invalid key) that was never
retried to begin with, the exception propagated straight out of the
generator and crashed the SSE response uncaught - the client just saw the
connection drop, indistinguishable from its own network failing, with
nothing logged server-side either. See PLAN.md's "Retry/backoff sur les
appels LLM" entry. No real network call: timed_stream_chat is monkeypatched
to raise directly."""

import httpx2
import pytest
from openai import RateLimitError

import server
from triton.storage import settings

_REQUEST = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")


def test_run_chat_stream_surfaces_an_exhausted_retry_as_a_clean_error(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)

    def fake_timed_stream_chat(*_args, **_kwargs):
        raise RateLimitError(
            "rate limited",
            response=httpx2.Response(429, request=_REQUEST),
            body=None,
        )

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    session_path = tmp_path / "sessions" / "test.json"
    session_path.parent.mkdir(parents=True)
    events = list(server.run_chat_stream(session_path, [{"role": "user", "content": "hi"}]))

    # exactly "session" then "error" - one clean failed iteration, no
    # retry loop inside run_chat_stream itself (llm/api.py already did
    # its own retrying before this exception ever reached here) and no
    # crash propagating out of the generator uncaught
    assert len(events) == 2
    assert "event: session" in events[0]
    assert "event: error" in events[1]
    assert "rate limited" in events[1]
