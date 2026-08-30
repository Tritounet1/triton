"""export_session_as_markdown turns a stored session's raw message dicts
into a readable transcript for sharing/archiving outside sessions/ (not
versioned). Exercised directly on message dicts, no session file or
network call needed."""

from server import export_session_as_markdown


def test_plain_text_turn():
    messages: list[dict[str, object]] = [
        {"role": "system", "content": "You are a concise and clear assistant."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello", "model": "anthropic/claude-haiku-4.5"},
    ]
    md = export_session_as_markdown(messages, "Test")

    assert md.startswith("# Test\n")
    assert "**Vous**" in md
    assert "hi" in md
    assert "**Triton** (anthropic/claude-haiku-4.5)" in md
    assert "hello" in md
    # system messages are internal, never part of the exported transcript
    assert "concise and clear" not in md


def test_tool_call_rendered_as_blockquote_with_its_result():
    messages = [
        {"role": "user", "content": "what's the capital of France?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "web_search", "arguments": '{"query": "capital"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "Paris is the capital."},
        {"role": "assistant", "content": "Paris.", "model": "test-model"},
    ]
    md = export_session_as_markdown(messages, "Test")

    assert '> 🔧 `web_search({"query": "capital"})`' in md
    assert "> Paris is the capital." in md
    # raw tool role messages aren't rendered as their own turn
    assert md.count("**Vous**") == 1


def test_attachment_shows_a_placeholder_not_the_raw_data():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "here's my CV"},
                {
                    "type": "file",
                    "file": {
                        "filename": "cv.pdf",
                        "file_data": "data:application/pdf;base64," + "A" * 10_000,
                    },
                },
            ],
        },
    ]
    md = export_session_as_markdown(messages, "Test")

    assert "here's my CV" in md
    assert "fichier joint : cv.pdf" in md
    assert "A" * 10_000 not in md


def test_image_attachment_shows_a_placeholder():
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ],
        },
    ]
    md = export_session_as_markdown(messages, "Test")
    assert "image jointe" in md
    assert "AAAA" not in md


def test_separator_between_turns_but_not_within_one():
    messages: list[dict[str, object]] = [
        {"role": "user", "content": "turn one"},
        {"role": "assistant", "content": "reply one", "model": "test-model"},
        {"role": "user", "content": "turn two"},
        {"role": "assistant", "content": "reply two", "model": "test-model"},
    ]
    md = export_session_as_markdown(messages, "Test")
    assert md.count("---") == 1
    assert not md.strip().startswith("---")
