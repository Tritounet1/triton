"""enforce_project_sandbox is the only thing standing between a project-
scoped conversation and a model that decides to read/write outside the
folder it was given - see PLAN.md's "Securite" entry for why this deserves
solid coverage rather than only manual testing."""

from triton.storage.projects import Project
from triton.tools import enforce_project_sandbox


def _project(tmp_path) -> Project:
    folder = tmp_path / "myproject"
    folder.mkdir()
    return Project(id="p1", name="myproject", folder_path=str(folder))


def test_no_project_scoped_allows_any_path():
    assert enforce_project_sandbox("read_file", {"path": "/etc/passwd"}, None) is None


def test_tool_not_in_sandboxed_list_is_unaffected(tmp_path):
    project = _project(tmp_path)
    assert enforce_project_sandbox("web_search", {"query": "anything"}, project) is None


def test_run_shell_directory_defaults_to_project_root(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"command": "ls"}
    assert enforce_project_sandbox("run_shell", args, project) is None
    assert args["directory"] == str((tmp_path / "myproject").resolve())


def test_run_shell_directory_outside_project_is_rejected(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"command": "ls", "directory": str(tmp_path)}
    error = enforce_project_sandbox("run_shell", args, project)
    assert error is not None


def test_run_tests_path_and_directory_both_checked(tmp_path):
    project = _project(tmp_path)
    root = tmp_path / "myproject"

    args: dict[str, object] = {"path": str(root / "tests")}
    assert enforce_project_sandbox("run_tests", args, project) is None
    assert args["directory"] == str(root.resolve())

    bad_path = enforce_project_sandbox("run_tests", {"path": str(tmp_path / "tests")}, project)
    assert bad_path is not None


def test_path_inside_project_is_allowed(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"path": str(tmp_path / "myproject" / "notes.md")}
    assert enforce_project_sandbox("read_file", args, project) is None


def test_relative_path_resolved_against_project_root(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"path": "notes.md"}
    assert enforce_project_sandbox("read_file", args, project) is None


def test_absolute_path_outside_project_is_rejected(tmp_path):
    project = _project(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    args: dict[str, object] = {"path": str(outside)}
    error = enforce_project_sandbox("read_file", args, project)
    assert error is not None
    assert "outside of it" in error


def test_relative_path_escaping_via_dotdot_is_rejected(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"path": "../elsewhere.txt"}
    error = enforce_project_sandbox("read_file", args, project)
    assert error is not None


def test_move_file_checks_both_source_and_destination(tmp_path):
    project = _project(tmp_path)
    root = tmp_path / "myproject"

    ok = enforce_project_sandbox(
        "move_file", {"source": str(root / "a"), "destination": str(root / "b")}, project
    )
    assert ok is None

    bad_destination = enforce_project_sandbox(
        "move_file", {"source": str(root / "a"), "destination": str(tmp_path / "b")}, project
    )
    assert bad_destination is not None


def test_git_commit_checks_every_path_in_a_list_argument(tmp_path):
    project = _project(tmp_path)
    root = tmp_path / "myproject"

    args = {"directory": str(root), "paths": [str(root / "a.py"), str(tmp_path / "b.py")]}
    error = enforce_project_sandbox("git_commit", args, project)
    assert error is not None


def test_omitted_directory_defaults_to_project_root_when_defaultable(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {}
    error = enforce_project_sandbox("list_files", args, project)
    assert error is None
    assert args["directory"] == str((tmp_path / "myproject").resolve())


def test_omitted_path_is_not_defaulted_when_not_in_defaultable_set(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {}
    error = enforce_project_sandbox("read_file", args, project)
    assert error is None
    assert "path" not in args
