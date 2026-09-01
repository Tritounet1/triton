"""run_code: a standalone Python/JavaScript snippet through a real
interpreter, no persistent state between calls. Real subprocess calls
here (sys.executable is a genuine interpreter in this dev/test
environment, same as running `uv run pytest`) rather than mocked, mirrors
this codebase's existing precedent for other subprocess-based tools (e.g.
test_snapshot.py actually shells out to real git)."""

import shutil

import pytest

from triton.tools import process

NODE_AVAILABLE = shutil.which("node") is not None


def test_runs_python_by_default():
    assert process.run_code("print(1 + 1)") == "2"


def test_runs_python_explicitly():
    assert process.run_code("print('hi')", language="python") == "hi"


def test_captures_stderr_too():
    result = process.run_code("import sys; sys.stderr.write('oops')")
    assert "oops" in result


def test_unsupported_language_is_a_clear_error():
    result = process.run_code("print(1)", language="ruby")
    assert result == "error: unsupported language 'ruby' - use 'python' or 'javascript'"


def test_no_output_reports_the_exit_code():
    result = process.run_code("import sys; sys.exit(3)")
    assert result == "(no output, exit code 3)"


def test_directory_sets_the_working_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("found")
    result = process.run_code("print(open('marker.txt').read())", directory=str(tmp_path))
    assert result == "found"


def test_output_is_truncated_past_the_configured_limit(monkeypatch):
    monkeypatch.setattr(process, "RUN_CODE_MAX_OUTPUT_CHARS", 20)
    result = process.run_code("print('x' * 100)")
    assert result.endswith("\n(truncated)")
    assert len(result) < 100


def test_timeout_is_reported(monkeypatch):
    monkeypatch.setattr(process, "RUN_CODE_TIMEOUT_SECONDS", 0.2)
    result = process.run_code("import time; time.sleep(5)")
    assert result == "error: code took too long (0.2s timeout)"


@pytest.mark.skipif(not NODE_AVAILABLE, reason="node not installed on this machine")
def test_runs_javascript():
    assert process.run_code("console.log(1 + 1)", language="javascript") == "2"


@pytest.mark.parametrize("alias", ["py", "js", "node"])
def test_language_aliases_resolve(alias, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(process, "_interpreter", lambda lang: seen.append(lang) or None)
    process.run_code("ignored", language=alias)
    assert seen == [{"py": "python", "js": "javascript", "node": "javascript"}[alias]]


# --- _python_interpreter: sys.executable vs. a frozen (PyInstaller) build ---


def test_python_interpreter_uses_sys_executable_when_not_frozen(monkeypatch):
    monkeypatch.setattr(process.sys, "frozen", False, raising=False)
    assert process._python_interpreter() == [process.sys.executable]


def test_python_interpreter_falls_back_to_path_when_frozen(monkeypatch):
    monkeypatch.setattr(process.sys, "frozen", True, raising=False)
    monkeypatch.setattr(
        process.shutil, "which", lambda name: "/usr/bin/python3" if name == "python3" else None
    )
    assert process._python_interpreter() == ["/usr/bin/python3"]


def test_python_interpreter_is_none_when_frozen_and_nothing_on_path(monkeypatch):
    monkeypatch.setattr(process.sys, "frozen", True, raising=False)
    monkeypatch.setattr(process.shutil, "which", lambda _name: None)
    assert process._python_interpreter() is None


def test_run_code_reports_missing_interpreter(monkeypatch):
    monkeypatch.setattr(process, "_interpreter", lambda _lang: None)
    assert process.run_code("print(1)") == "error: no python interpreter found on this system"
