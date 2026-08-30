"""compress_history_if_needed is the piece most likely to silently regress
across a refactor: it decides which messages survive, and a mistake there
either loses real conversation content or corrupts the assistant/tool_calls
pairing the API requires. No network call needed - call_chat is monkeypatched
so summarize() never actually hits the model."""

from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from triton import chat_loop
from triton.api import ChatResult


def _user(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "user", "content": text})


def _assistant(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "assistant", "content": text})


def _system(text: str) -> ChatCompletionMessageParam:
    return cast(ChatCompletionMessageParam, {"role": "system", "content": text})


def test_turn_start_indices_finds_user_messages_only():
    messages = [_system("s"), _user("a"), _assistant("b"), _user("c")]
    assert chat_loop.turn_start_indices(messages) == [1, 3]


def test_short_history_is_left_untouched():
    messages = [_system("s"), _user("hi"), _assistant("hello")]
    compressed, log_message = chat_loop.compress_history_if_needed(messages)
    assert compressed == messages
    assert log_message is None


def test_few_turns_are_never_compressed_even_if_oversized(monkeypatch):
    """KEEP_RECENT_TURNS turns or fewer must survive uncompressed, even past
    MAX_CONTEXT_CHARS - there would be nothing left to summarize without
    also cutting into the turns compress_history_if_needed promises to
    keep intact."""

    def _fail_if_called(*_args: object, **_kwargs: object) -> ChatResult:
        raise AssertionError("summarize() must not run when there's nothing to compress")

    monkeypatch.setattr(chat_loop, "call_chat", _fail_if_called)

    huge = "x" * (chat_loop.MAX_CONTEXT_CHARS * 2)
    messages = [_system("s"), _user(huge), _assistant("ok")]
    compressed, log_message = chat_loop.compress_history_if_needed(messages)
    assert compressed == messages
    assert log_message is None


def test_oversized_history_compresses_oldest_turns_only(monkeypatch):
    monkeypatch.setattr(chat_loop, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(chat_loop, "estimate_cost", lambda *_args: None)
    monkeypatch.setattr(
        chat_loop,
        "call_chat",
        lambda *_args, **_kwargs: ChatResult(
            content="summary of the old turns",
            tool_calls=[],
            model="test-model",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        ),
    )

    filler = "x" * 1000
    messages = [
        _system("system prompt"),
        _user(f"turn 1 {filler}"),
        _assistant(f"reply 1 {filler}"),
        _user(f"turn 2 {filler}"),
        _assistant(f"reply 2 {filler}"),
        _user(f"turn 3 {filler}"),
        _assistant(f"reply 3 {filler}"),
        _user(f"turn 4 {filler}"),
        _assistant(f"reply 4 {filler}"),
    ]
    assert chat_loop.estimate_size(messages) > chat_loop.MAX_CONTEXT_CHARS

    compressed, log_message = chat_loop.compress_history_if_needed(messages)

    assert log_message == "history compressed: 2 messages summarized into 1"
    # system prompt kept first, then the inserted summary, then exactly the
    # last KEEP_RECENT_TURNS turns (turn 2 onward) untouched
    assert compressed[0] == messages[0]
    assert compressed[1]["role"] == "system"
    assert "summary of the old turns" in cast(str, compressed[1]["content"])
    assert compressed[2:] == messages[3:]


def test_summarize_redacts_attachments_instead_of_resending_them(monkeypatch):
    """Regression test: summarizing old turns that included an image/PDF
    used to re-send that attachment's full base64 data as part of the
    "please summarize this" prompt - found via a real ~900k-token, ~1-
    minute compression call for what should have been a cheap, fast
    summary. The transcript actually sent to the model must carry a
    placeholder instead of the raw attachment data."""
    captured: list[list[ChatCompletionMessageParam]] = []

    def _capture(messages: list[ChatCompletionMessageParam], **_kwargs: object) -> ChatResult:
        captured.append(messages)
        return ChatResult(
            content="summary",
            tool_calls=[],
            model="test-model",
            prompt_tokens=1,
            completion_tokens=1,
            total_tokens=2,
        )

    monkeypatch.setattr(chat_loop, "log_event", lambda **_kwargs: None)
    monkeypatch.setattr(chat_loop, "estimate_cost", lambda *_args: None)
    monkeypatch.setattr(chat_loop, "call_chat", _capture)

    huge_base64_payload = "A" * 500_000
    old_messages: list[ChatCompletionMessageParam] = [
        cast(
            ChatCompletionMessageParam,
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "here's my CV"},
                    {
                        "type": "file",
                        "file": {
                            "filename": "cv.pdf",
                            "file_data": f"data:application/pdf;base64,{huge_base64_payload}",
                        },
                    },
                ],
            },
        ),
    ]

    chat_loop.summarize(old_messages)

    assert len(captured) == 1
    transcript = cast(str, captured[0][1].get("content"))
    assert huge_base64_payload not in transcript
    assert "cv.pdf" in transcript
    assert "here's my CV" in transcript
