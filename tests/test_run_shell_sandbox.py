"""run_shell (and run_code/run_tests via the same _run_confined helper)
now wraps its subprocess in sandbox-exec (Seatbelt) on macOS whenever a
directory is given, confining filesystem *writes* to that directory plus
a small set of well-known cache/temp dirs - closing the `cd .. && rm -rf`
escape a real conversation was demonstrated trying (see PLAN.md's "Vrai
bac a sable pour run_shell" entry). Real subprocess/sandbox-exec calls
here, no mocking - this kind of enforcement is only actually verified by
running real commands against it, not by asserting on its own logic in
isolation (the exact allow-list below was arrived at the same way: a
first draft broke `git status`, Python's tempfile module, and
`npm install` until each was tested directly and fixed)."""

import sys
import tempfile
from pathlib import Path

import pytest

from triton.tools import process
from triton.tools.process import run_shell

macos_only = pytest.mark.skipif(sys.platform != "darwin", reason="sandbox-exec is macOS-only")


@pytest.fixture
def outside_tmpdir():
    """A scratch directory under the *system-wide* /tmp (resolved:
    /private/tmp), deliberately not under pytest's own tmp_path - that
    fixture nests under tempfile.gettempdir() (resolved:
    /private/var/folders/.../T on macOS), which the sandbox profile
    explicitly allows writes to (many real tools need it - see
    _MACOS_SANDBOX_PROFILE), so an "escape" landing there wouldn't
    actually prove anything got blocked."""
    with tempfile.TemporaryDirectory(dir="/tmp") as d:
        yield Path(d).resolve()


@macos_only
def test_write_inside_the_directory_succeeds(tmp_path):
    result = run_shell("echo hello > inside.txt && cat inside.txt", directory=str(tmp_path))

    assert result == "hello"
    assert (tmp_path / "inside.txt").read_text() == "hello\n"


@macos_only
def test_write_outside_via_cd_dotdot_is_blocked(outside_tmpdir):
    project = outside_tmpdir / "project"
    project.mkdir()

    run_shell("cd .. && touch escape.txt", directory=str(project))

    assert not (outside_tmpdir / "escape.txt").exists()


@macos_only
def test_write_outside_via_absolute_path_is_blocked(outside_tmpdir):
    project = outside_tmpdir / "project"
    project.mkdir()
    outside = outside_tmpdir / "outside.txt"

    run_shell(f"touch {outside}", directory=str(project))

    assert not outside.exists()


@macos_only
def test_deleting_a_file_inside_the_directory_still_works(tmp_path):
    (tmp_path / "a.txt").write_text("x")

    run_shell("rm a.txt", directory=str(tmp_path))

    assert not (tmp_path / "a.txt").exists()


@macos_only
def test_nested_mkdir_and_write_inside_the_directory_still_works(tmp_path):
    result = run_shell(
        "mkdir -p a/b/c && echo hi > a/b/c/f.txt && cat a/b/c/f.txt", directory=str(tmp_path)
    )

    assert result == "hi"


@macos_only
def test_reads_outside_the_directory_still_work(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("readable")
    project = tmp_path / "project"
    project.mkdir()

    result = run_shell(f"cat {outside}", directory=str(project))

    assert result == "readable"


@macos_only
def test_writing_to_the_resolved_tmp_dir_still_works(tmp_path):
    """Python's own tempfile module (and many real tools - compilers,
    package managers) need this; a project-folder-only profile broke it
    until TMP_DIR was added to the allow-list."""
    result = run_shell(
        'python3 -c "import tempfile; f=tempfile.NamedTemporaryFile(delete=False); '
        "f.write(b'x'); print('tmp-ok')\"",
        directory=str(tmp_path),
    )

    assert result == "tmp-ok"


def test_non_macos_platforms_keep_the_old_cwd_only_confinement(monkeypatch, tmp_path):
    """Not macOS-only: monkeypatches the platform check itself, so this
    runs regardless of the host OS - confirms _run_confined's fallback
    branch (no sandbox-exec available) still works at all, and is
    honestly unconfined beyond cwd, matching the documented limitation
    for Linux/Windows."""
    monkeypatch.setattr(process.sys, "platform", "linux")
    project = tmp_path / "project"
    project.mkdir()

    run_shell("cd .. && touch escape.txt", directory=str(project))

    assert (tmp_path / "escape.txt").exists()
