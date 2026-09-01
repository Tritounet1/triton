"""edit_file applies one or more {path, old_string, new_string, replace_all?}
edits, across one or more files, in a single call. Edits for the same
path are applied in order against that file's running content (multi-hunk);
different paths are independent (multi-file) - each file succeeds or fails
on its own, so one failing file doesn't block the others."""

from triton.tools.filesystem import edit_file


def test_single_edit_still_works(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("hello world")

    result = edit_file([{"path": str(f), "old_string": "world", "new_string": "there"}])

    assert f.read_text() == "hello there"
    assert result == f"{f}: 1 edit(s) applied"


def test_multiple_hunks_in_the_same_file_apply_in_order(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("one two three")

    result = edit_file(
        [
            {"path": str(f), "old_string": "one", "new_string": "1"},
            {"path": str(f), "old_string": "three", "new_string": "3"},
        ]
    )

    assert f.read_text() == "1 two 3"
    assert result == f"{f}: 2 edit(s) applied"


def test_second_hunk_operates_on_the_first_hunks_result(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("aaa")

    # the second hunk's old_string only exists after the first hunk runs
    result = edit_file(
        [
            {"path": str(f), "old_string": "aaa", "new_string": "abc"},
            {"path": str(f), "old_string": "abc", "new_string": "xyz"},
        ]
    )

    assert f.read_text() == "xyz"
    assert result == f"{f}: 2 edit(s) applied"


def test_multiple_files_in_one_call(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("apple")
    b.write_text("banana")

    result = edit_file(
        [
            {"path": str(a), "old_string": "apple", "new_string": "apricot"},
            {"path": str(b), "old_string": "banana", "new_string": "blueberry"},
        ]
    )

    assert a.read_text() == "apricot"
    assert b.read_text() == "blueberry"
    assert result == f"{a}: 1 edit(s) applied\n{b}: 1 edit(s) applied"


def test_one_failing_file_does_not_block_the_others(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("apple")
    b.write_text("banana")

    result = edit_file(
        [
            {"path": str(a), "old_string": "does-not-exist", "new_string": "x"},
            {"path": str(b), "old_string": "banana", "new_string": "blueberry"},
        ]
    )

    assert a.read_text() == "apple"  # untouched
    assert b.read_text() == "blueberry"  # still applied
    assert f"{a}: error: old_string not found" in result
    assert f"{b}: 1 edit(s) applied" in result


def test_a_failing_hunk_leaves_that_file_completely_untouched(tmp_path):
    """Atomicity per file: hunk 1 succeeding then hunk 2 failing must not
    leave the file half-edited on disk."""
    f = tmp_path / "a.txt"
    f.write_text("one two")

    result = edit_file(
        [
            {"path": str(f), "old_string": "one", "new_string": "1"},
            {"path": str(f), "old_string": "does-not-exist", "new_string": "x"},
        ]
    )

    assert f.read_text() == "one two"
    assert "hunk 2/2" in result


def test_ambiguous_old_string_fails_without_replace_all(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("aa")

    result = edit_file([{"path": str(f), "old_string": "a", "new_string": "b"}])

    assert f.read_text() == "aa"
    assert "matches 2 times" in result


def test_replace_all_replaces_every_occurrence(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("aa")

    result = edit_file(
        [{"path": str(f), "old_string": "a", "new_string": "b", "replace_all": True}]
    )

    assert f.read_text() == "bb"
    assert result == f"{f}: 1 edit(s) applied"


def test_no_edits_is_an_error():
    assert edit_file([]) == "error: no edits provided"


def test_edit_missing_path_is_reported_by_position():
    result = edit_file([{"old_string": "a", "new_string": "b"}])
    assert result == "error: edit 1 is missing 'path'"


def test_edit_missing_old_or_new_string_is_reported():
    result = edit_file([{"path": "a.txt", "old_string": "a"}])
    assert "needs 'old_string' and 'new_string'" in result


def test_non_object_edit_is_reported():
    result = edit_file(["not a dict"])  # type: ignore[list-item]
    assert result == "error: edit 1 is not an object with path/old_string/new_string"


def test_unreadable_file_is_reported_and_other_files_still_apply(tmp_path):
    b = tmp_path / "b.txt"
    b.write_text("banana")

    result = edit_file(
        [
            {"path": str(tmp_path / "missing.txt"), "old_string": "x", "new_string": "y"},
            {"path": str(b), "old_string": "banana", "new_string": "blueberry"},
        ]
    )

    assert b.read_text() == "blueberry"
    assert "error: could not read" in result
