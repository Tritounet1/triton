from main import MAX_ARG_PREVIEW, format_args


def test_short_args_rendered_as_is():
    assert format_args({"path": "a.txt"}) == "path='a.txt'"


def test_multiple_args_joined_with_comma():
    assert format_args({"a": 1, "b": "x"}) == "a=1, b='x'"


def test_long_string_value_is_truncated_with_character_count():
    long_value = "y" * (MAX_ARG_PREVIEW + 50)
    rendered = format_args({"content": long_value})
    assert rendered.startswith('content="')
    assert f"({len(long_value)} characters total)" in rendered
    assert long_value not in rendered


def test_newlines_in_a_truncated_value_are_flattened():
    long_value = "line one\n" * 50
    rendered = format_args({"command": long_value})
    assert "\n" not in rendered
