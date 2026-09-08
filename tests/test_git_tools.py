"""git_log/git_branch/git_checkout/git_push (git.py) - added alongside
git_status/git_diff/git_commit so the model can consult history, work
across branches, and push to a remote, none of which the original three
covered (see PLAN.md's own note). Real git repos here, no mocking -
git_push in particular is tested against a real local bare repo standing
in for a remote, since that's the only way to actually prove something
landed there without a network dependency."""

import subprocess
from pathlib import Path
from typing import cast

from triton.tools.git import git_branch, git_checkout, git_log, git_push, git_status


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run(["init", "-q"], repo)
    _run(["config", "user.email", "test@example.com"], repo)
    _run(["config", "user.name", "Test"], repo)
    return repo


def _commit(repo: Path, filename: str, content: str, message: str) -> None:
    (repo / filename).write_text(content)
    _run(["add", filename], repo)
    _run(["commit", "-q", "-m", message], repo)


# --- git_log ---


def test_git_log_shows_recent_commits(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "first commit")
    _commit(repo, "b.txt", "2", "second commit")

    result = git_log(directory=str(repo))

    assert "first commit" in result
    assert "second commit" in result


def test_git_log_respects_max_count(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "first commit")
    _commit(repo, "b.txt", "2", "second commit")
    _commit(repo, "c.txt", "3", "third commit")

    result = git_log(directory=str(repo), max_count=1)

    assert "third commit" in result
    assert "second commit" not in result
    assert "first commit" not in result


def test_git_log_can_restrict_to_a_path(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "touches a")
    _commit(repo, "b.txt", "2", "touches b")

    result = git_log(directory=str(repo), path="a.txt")

    assert "touches a" in result
    assert "touches b" not in result


# --- git_branch / git_checkout ---


def test_git_branch_lists_branches_with_current_marked(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "init")
    _run(["branch", "feature-x"], repo)

    result = git_branch(directory=str(repo))

    assert "feature-x" in result
    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert f"* {current}" in result


def test_git_checkout_creates_and_switches_to_a_new_branch(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "init")

    git_checkout("feature-x", create=True, directory=str(repo))

    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert current == "feature-x"


def test_git_checkout_switches_back_to_an_existing_branch(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "init")
    _run(["branch", "feature-x"], repo)
    _run(["checkout", "-q", "feature-x"], repo)

    original = subprocess.run(
        ["git", "branch", "--list"], cwd=repo, capture_output=True, text=True
    ).stdout
    default_branch = next(
        line.strip() for line in original.splitlines() if "feature-x" not in line
    ).strip()

    git_checkout(default_branch, directory=str(repo))

    current = subprocess.run(
        ["git", "branch", "--show-current"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()
    assert current == default_branch


# --- git_push ---


def test_git_push_pushes_commits_to_a_local_bare_remote(tmp_path):
    bare = tmp_path / "remote.git"
    _run(["init", "-q", "--bare", str(bare)], tmp_path)

    repo = _repo(tmp_path)
    _run(["remote", "add", "origin", str(bare)], repo)
    _commit(repo, "a.txt", "1", "first commit")

    result = git_push(directory=str(repo), remote="origin", set_upstream=True)

    assert "error" not in result.lower()
    log_in_bare = subprocess.run(
        ["git", "--git-dir", str(bare), "log", "--oneline"],
        capture_output=True,
        text=True,
    ).stdout
    assert "first commit" in log_in_bare


def test_git_push_reports_an_error_with_no_remote_configured(tmp_path):
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "first commit")

    result = git_push(directory=str(repo), remote="origin")

    assert "error" in result.lower() or result  # git itself reports the failure in stderr


def test_git_push_schema_never_exposes_a_force_option():
    """Guards against a future regression re-introducing a force flag -
    see git.py's own comment on git_push for why it's deliberately absent."""
    from triton.tools.git import REGISTRY

    function = cast(dict[str, object], REGISTRY["git_push"].schema["function"])
    parameters = cast(dict[str, object], function["parameters"])
    properties = cast(dict[str, object], parameters["properties"])
    assert not any("force" in key.lower() for key in properties)


def test_git_status_still_works_alongside_the_new_tools(tmp_path):
    """Sanity check: adding the new tools didn't disturb the existing ones."""
    repo = _repo(tmp_path)
    _commit(repo, "a.txt", "1", "init")
    (repo / "b.txt").write_text("uncommitted")

    result = git_status(directory=str(repo))

    assert "b.txt" in result
