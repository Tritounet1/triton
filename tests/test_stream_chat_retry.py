"""stream_chat's own retry-if-nothing-produced-yet loop: found via a real
conversation where a stream died right after opening (observed message:
"The operation was aborted"), before a single chunk carrying real
content/tool-call data ever arrived - past _with_retry's scope (only
covers the .create() call that opens the stream, not reading its body)
and past the point call sites like run_chat_stream could safely retry
themselves (tokens may already be relayed to the client as SSE by their
level). No real network call: _client().chat.completions.create is
monkeypatched to a fake that dies on its first call and/or succeeds on a
later one."""

from types import SimpleNamespace

import httpx2
import pytest
from openai import RateLimitError

from triton.llm import api

_REQUEST = httpx2.Request("POST", "https://openrouter.ai/api/v1/chat/completions")


def _response(status_code: int) -> httpx2.Response:
    return httpx2.Response(status_code=status_code, request=_REQUEST)


def _chunk(content: str | None = None, finish_reason: str | None = None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=[])
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(model="test-model", choices=[choice], usage=usage)


def _usage(prompt: int, completion: int, total: int):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _fake_client(create):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr(api.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(api, "get_model", lambda: "test-model")


def test_a_stream_that_dies_before_any_chunk_is_retried_from_scratch(monkeypatch):
    call_count = 0

    def fake_create(**_kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:

            def _dies_immediately():
                raise RateLimitError("rate limited", response=_response(429), body=None)
                yield  # pragma: no cover - unreachable, keeps this a generator

            return _dies_immediately()
        return iter([_chunk(content="Hello"), _chunk(finish_reason="stop", usage=_usage(1, 1, 2))])

    monkeypatch.setattr(api, "_client", lambda: _fake_client(fake_create))

    events = list(api.stream_chat([{"role": "user", "content": "hi"}]))
    text_events = [e for e in events if isinstance(e, str)]
    result = events[-1]

    assert call_count == 2
    assert text_events == ["Hello"]
    assert isinstance(result, api.ChatResult)
    assert result.content == "Hello"


def test_gives_up_after_max_retries_if_still_producing_nothing(monkeypatch):
    call_count = 0

    def fake_create(**_kwargs):
        nonlocal call_count
        call_count += 1

        def _dies_immediately():
            raise RateLimitError("rate limited", response=_response(429), body=None)
            yield  # pragma: no cover - unreachable

        return _dies_immediately()

    monkeypatch.setattr(api, "_client", lambda: _fake_client(fake_create))

    with pytest.raises(RateLimitError):
        list(api.stream_chat([{"role": "user", "content": "hi"}]))

    # the first attempt plus MAX_RETRIES retries, never more
    assert call_count == api.MAX_RETRIES + 1


def test_a_stream_that_dies_after_producing_output_is_not_retried(monkeypatch):
    """Once real content has been yielded, it may already have reached
    the client as SSE - silently restarting the whole response from
    scratch at that point would risk duplicating it, so a failure past
    this point is left to raise as-is."""
    call_count = 0

    def fake_create(**_kwargs):
        nonlocal call_count
        call_count += 1

        def _partial_then_dies():
            yield _chunk(content="Hello")
            raise RateLimitError("rate limited", response=_response(429), body=None)

        return _partial_then_dies()

    monkeypatch.setattr(api, "_client", lambda: _fake_client(fake_create))

    events = []
    with pytest.raises(RateLimitError):
        for event in api.stream_chat([{"role": "user", "content": "hi"}]):
            events.append(event)

    assert events == ["Hello"]
    assert call_count == 1


def test_a_non_transient_error_with_no_output_is_not_retried(monkeypatch):
    call_count = 0

    def fake_create(**_kwargs):
        nonlocal call_count
        call_count += 1

        def _dies_immediately():
            raise ValueError("not an API error at all")
            yield  # pragma: no cover - unreachable

        return _dies_immediately()

    monkeypatch.setattr(api, "_client", lambda: _fake_client(fake_create))

    with pytest.raises(ValueError):
        list(api.stream_chat([{"role": "user", "content": "hi"}]))

    assert call_count == 1
