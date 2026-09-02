"""run_chat_stream's handling of a reply with neither content nor a tool
call. Two distinct causes, both recoverable the same way (nudge the
model and let the loop retry, bounded by MAX_CONSECUTIVE_EMPTY_REPLIES):
finish_reason == "length" (a reasoning model burning its whole token
budget on hidden reasoning) already had this handling; a genuinely empty
completion with no exception raised at all (llm/api.py's own retrying
never even sees it - found via a real conversation, google/gemini-3.7-
flash, twice in one session, one attempt taking 74s) did not, and used
to hard-stop the turn on the first occurrence, needing a manual
"continue". No real model call: timed_stream_chat is monkeypatched to a
fake reply sequence."""

import pytest

import server
from triton.llm.api import ChatResult
from triton.storage import sessions, settings


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(sessions, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(server, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(settings, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(server, "is_api_key_configured", lambda: True)


def _empty_reply(finish_reason: str | None) -> ChatResult:
    return ChatResult(
        content=None,
        tool_calls=[],
        model="test-model",
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        finish_reason=finish_reason,
    )


def _text_reply(text: str) -> ChatResult:
    return ChatResult(
        content=text,
        tool_calls=[],
        model="test-model",
        prompt_tokens=1,
        completion_tokens=1,
        total_tokens=2,
        finish_reason="stop",
    )


def _session_path(tmp_path):
    path = tmp_path / "sessions" / "test.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _stream_stub(monkeypatch, replies):
    """Each call to timed_stream_chat yields the next reply in `replies`
    (a fresh generator each time, matching the real one's own contract);
    the last reply is repeated indefinitely once exhausted, so a broken
    test doesn't hang the whole suite instead of failing loudly."""
    calls: list[int] = []

    def fake_timed_stream_chat(*_args, **_kwargs):
        calls.append(1)
        index = min(len(calls) - 1, len(replies) - 1)
        yield replies[index]

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)
    return calls


def test_length_truncated_reply_is_retried_with_a_nudge(tmp_path, monkeypatch):
    calls = _stream_stub(monkeypatch, [_empty_reply(finish_reason="length"), _text_reply("done")])

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    assert len(calls) == 2
    assert any("cut off by the output length limit" in e for e in events)
    assert any("event: done" in e for e in events)


def test_a_genuinely_empty_reply_is_also_retried_with_a_nudge(tmp_path, monkeypatch):
    """The actual reported bug: no exception, no finish_reason == "length"
    - just nothing at all. Must recover the same way, not hard-stop on
    the first occurrence."""
    calls = _stream_stub(monkeypatch, [_empty_reply(finish_reason="stop"), _text_reply("done")])

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    assert len(calls) == 2
    assert any("the model returned an empty response" in e for e in events)
    assert any("event: done" in e for e in events)
    assert not any("giving up" in e for e in events)


def test_stops_after_too_many_consecutive_empty_replies(tmp_path, monkeypatch):
    calls = _stream_stub(monkeypatch, [_empty_reply(finish_reason="stop")])

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    assert len(calls) == server.MAX_CONSECUTIVE_EMPTY_REPLIES + 1
    error_events = [e for e in events if "event: error" in e]
    assert len(error_events) == 1
    assert "giving up" in error_events[0]


def test_a_real_reply_resets_the_empty_streak(tmp_path, monkeypatch):
    """An empty reply followed by a real one, repeated - never trips the
    hard stop since the streak keeps resetting."""
    call_count = 0

    def fake_timed_stream_chat(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count % 2 == 1:
            yield _empty_reply(finish_reason="stop")
        else:
            yield _text_reply(f"reply {call_count}")

    monkeypatch.setattr(server, "timed_stream_chat", fake_timed_stream_chat)

    events = list(
        server.run_chat_stream(_session_path(tmp_path), [{"role": "user", "content": "hi"}])
    )

    assert not any("giving up" in e for e in events)
    assert any("event: done" in e for e in events)
