"""run_shell's timeout used to be a hardcoded 10 seconds - genuinely too
low for the real one-off commands this tool is meant for (package
installs, scaffolding a new project with create-next-app...), found via
a real conversation where an entirely ordinary `npx create-next-app`
failed outright with "command took too long (10s timeout)". No real
subprocess here: _run_confined is monkeypatched to capture the timeout
it's called with, or to simulate a real timeout."""

import subprocess

from triton.tools import process


def test_run_shell_passes_the_configured_timeout_to_run_confined(monkeypatch):
    captured = {}

    def fake_run_confined(command, directory, timeout):
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(process, "_run_confined", fake_run_confined)

    process.run_shell("echo ok", directory=".")

    assert captured["timeout"] == process.RUN_SHELL_TIMEOUT_SECONDS


def test_run_shell_timeout_is_generous_enough_for_real_commands():
    """Regression guard for the exact bug: 10s was routinely too short
    for a real package install/scaffold command."""
    assert process.RUN_SHELL_TIMEOUT_SECONDS >= 60


def test_run_shell_timeout_message_reflects_the_configured_value(monkeypatch):
    def fake_run_confined(command, directory, timeout):
        raise subprocess.TimeoutExpired(cmd=command, timeout=timeout)

    monkeypatch.setattr(process, "_run_confined", fake_run_confined)

    result = process.run_shell("sleep 999", directory=".")

    assert result == f"error: command took too long ({process.RUN_SHELL_TIMEOUT_SECONDS}s timeout)"
