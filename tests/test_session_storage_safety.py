"""Session IDs and JSON writes must not turn into filesystem hazards."""

import json

import pytest

from triton.storage import sessions


def test_session_path_rejects_path_like_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")

    for invalid_id in ("../settings", "..", "session.json", "/tmp/session", "a/b"):
        with pytest.raises(ValueError, match="invalid session id"):
            sessions.session_path(invalid_id)


def test_new_sessions_are_unique_even_in_the_same_second(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSIONS_DIR", tmp_path / "sessions")

    first = sessions.new_session_path()
    second = sessions.new_session_path()

    assert first != second
    assert sessions.SESSION_ID_PATTERN.fullmatch(first.stem)
    assert sessions.SESSION_ID_PATTERN.fullmatch(second.stem)


def test_failed_atomic_session_save_keeps_the_previous_valid_json(tmp_path, monkeypatch):
    path = tmp_path / "session.json"
    original = [{"role": "user", "content": "before"}]
    path.write_text(json.dumps(original))

    def fail_replace(*_args):
        raise OSError("simulated crash before replacement")

    monkeypatch.setattr(sessions.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated crash"):
        sessions.save_session(path, [{"role": "user", "content": "after"}])

    assert json.loads(path.read_text()) == original
    assert not list(tmp_path.glob(".session.json.*"))
