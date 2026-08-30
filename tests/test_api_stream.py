"""Regression coverage for the finish_reason == "length" truncation bug:
before ChatResult tracked finish_reason at all, a reasoning model burning
its whole token budget on hidden reasoning (empty content, no tool call)
was indistinguishable from a genuinely empty/broken response, so
run_chat_stream (server.py) had no way to tell the two apart and retry.
stream_chat's chunk-accumulation loop is where that field is captured, so
that's what these tests pin down - with a fake stream, no network call."""

from types import SimpleNamespace

from openai.types.chat import ChatCompletionMessageFunctionToolCall

from triton import api


def _chunk(
    model: str = "test-model",
    content: str | None = None,
    finish_reason: str | None = None,
    tool_call_delta=None,
    usage=None,
):
    delta = SimpleNamespace(content=content, tool_calls=tool_call_delta or [])
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(model=model, choices=[choice], usage=usage)


def _usage(prompt: int, completion: int, total: int):
    return SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total)


def _fake_stream(chunks):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **_kwargs: iter(chunks)))
    )


def test_normal_response_collects_content_and_finish_reason(monkeypatch):
    monkeypatch.setattr(api, "get_model", lambda: "test-model")
    chunks = [
        _chunk(content="Hello"),
        _chunk(content=", world"),
        _chunk(finish_reason="stop", usage=_usage(10, 5, 15)),
    ]
    monkeypatch.setattr(api, "_client", lambda: _fake_stream(chunks))

    events = list(api.stream_chat([{"role": "user", "content": "hi"}]))
    text_events = [e for e in events if isinstance(e, str)]
    result = events[-1]
    assert isinstance(result, api.ChatResult)

    assert "".join(text_events) == "Hello, world"
    assert result.content == "Hello, world"
    assert result.finish_reason == "stop"
    assert result.total_tokens == 15


def test_truncated_response_reports_length_with_no_content(monkeypatch):
    """The exact regressed scenario: a reasoning model burns its entire
    token budget with nothing visible produced yet."""
    monkeypatch.setattr(api, "get_model", lambda: "test-model")
    chunks = [_chunk(finish_reason="length", usage=_usage(8000, 100, 8100))]
    monkeypatch.setattr(api, "_client", lambda: _fake_stream(chunks))

    events = list(api.stream_chat([{"role": "user", "content": "hi"}]))
    result = events[-1]
    assert isinstance(result, api.ChatResult)

    assert result.content is None
    assert result.tool_calls == []
    assert result.finish_reason == "length"


def test_tool_call_deltas_are_reassembled_across_chunks(monkeypatch):
    monkeypatch.setattr(api, "get_model", lambda: "test-model")
    first_delta = SimpleNamespace(
        index=0, id="call_1", function=SimpleNamespace(name="read_file", arguments='{"path')
    )
    second_delta = SimpleNamespace(
        index=0, id=None, function=SimpleNamespace(name=None, arguments='": "a.txt"}')
    )
    chunks = [
        _chunk(tool_call_delta=[first_delta]),
        _chunk(tool_call_delta=[second_delta], finish_reason="tool_calls"),
    ]
    monkeypatch.setattr(api, "_client", lambda: _fake_stream(chunks))

    events = list(api.stream_chat([{"role": "user", "content": "hi"}], tools=[]))
    result = events[-1]
    assert isinstance(result, api.ChatResult)

    assert len(result.tool_calls) == 1
    call = result.tool_calls[0]
    assert isinstance(call, ChatCompletionMessageFunctionToolCall)
    assert call.function.name == "read_file"
    assert call.function.arguments == '{"path": "a.txt"}'
