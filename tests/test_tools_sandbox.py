"""enforce_project_sandbox is the only thing standing between a
conversation and a model that decides to read/write outside the folder
it was given - or, with no project at all, outside of nothing at all,
before this had two more rules added: no project means every filesystem/
shell tool is blocked outright (previously it meant no restriction at
all - see PLAN.md's "Securite" entry, found via a real conversation with
no project writing/deleting a file directly in the harness's own repo),
and the harness's own installation directory (ROOT_DIR) is off-limits to
every tool call even inside a project deliberately scoped there."""

from triton.storage.projects import Project
from triton.tools import _shared as shared
from triton.tools import enforce_project_sandbox


def _project(tmp_path) -> Project:
    folder = tmp_path / "myproject"
    folder.mkdir()
    return Project(id="p1", name="myproject", folder_path=str(folder))


# --- no project: every filesystem/shell tool blocked, everything else unaffected ---


def test_no_project_scoped_blocks_a_filesystem_tool():
    error = enforce_project_sandbox("read_file", {"path": "/etc/passwd"}, None)
    assert error is not None
    assert "needs a project" in error


def test_no_project_scoped_blocks_every_filesystem_and_shell_tool():
    for tool_name in [*shared.SANDBOXED_PATH_ARGS, "edit_file"]:
        error = enforce_project_sandbox(tool_name, {}, None)
        assert error is not None, f"{tool_name} should be blocked without a project"


def test_no_project_scoped_leaves_non_filesystem_tools_alone():
    assert enforce_project_sandbox("web_search", {"query": "anything"}, None) is None
    assert enforce_project_sandbox("remember", {"note": "x"}, None) is None


def test_tool_not_in_sandboxed_list_is_unaffected(tmp_path):
    project = _project(tmp_path)
    assert enforce_project_sandbox("web_search", {"query": "anything"}, project) is None


# --- ROOT_DIR: off-limits even inside a project scoped there ---


def test_root_dir_is_blocked_even_when_a_project_is_scoped_there(tmp_path, monkeypatch):
    fake_root = tmp_path / "harness_install"
    fake_root.mkdir()
    monkeypatch.setattr(shared, "ROOT_DIR", fake_root)
    project = Project(id="p1", name="self", folder_path=str(fake_root))

    error = enforce_project_sandbox(
        "read_file", {"path": str(fake_root / "settings.json")}, project
    )

    assert error is not None
    assert "installation directory" in error


def test_root_dir_is_blocked_even_as_a_subpath_of_a_parent_project(tmp_path, monkeypatch):
    fake_root = tmp_path / "harness_install"
    fake_root.mkdir()
    monkeypatch.setattr(shared, "ROOT_DIR", fake_root)
    # the project folder is a *parent* of fake_root, so this path is
    # technically "inside the project" too - ROOT_DIR must still win
    project = Project(id="p1", name="parent", folder_path=str(tmp_path))

    error = enforce_project_sandbox(
        "read_file", {"path": str(fake_root / "settings.json")}, project
    )

    assert error is not None
    assert "installation directory" in error


def test_path_outside_root_dir_is_unaffected_by_the_root_dir_check(tmp_path, monkeypatch):
    fake_root = tmp_path / "harness_install"
    fake_root.mkdir()
    monkeypatch.setattr(shared, "ROOT_DIR", fake_root)
    project = _project(tmp_path)

    error = enforce_project_sandbox(
        "read_file", {"path": str(tmp_path / "myproject" / "a.py")}, project
    )

    assert error is None


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


def test_edit_file_allows_edits_within_the_project(tmp_path):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    args: dict[str, object] = {
        "edits": [{"path": str(root / "a.py"), "old_string": "x", "new_string": "y"}]
    }
    assert enforce_project_sandbox("edit_file", args, project) is None


def test_edit_file_rejects_a_path_outside_the_project(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {
        "edits": [{"path": str(tmp_path / "outside.py"), "old_string": "x", "new_string": "y"}]
    }
    error = enforce_project_sandbox("edit_file", args, project)
    assert error is not None


def test_edit_file_rejects_if_any_edit_in_the_batch_is_outside(tmp_path):
    project = _project(tmp_path)
    root = tmp_path / "myproject"
    args: dict[str, object] = {
        "edits": [
            {"path": str(root / "a.py"), "old_string": "x", "new_string": "y"},
            {"path": str(tmp_path / "outside.py"), "old_string": "x", "new_string": "y"},
        ]
    }
    error = enforce_project_sandbox("edit_file", args, project)
    assert error is not None


def test_edit_file_malformed_edits_do_not_crash(tmp_path):
    project = _project(tmp_path)
    assert enforce_project_sandbox("edit_file", {"edits": "not a list"}, project) is None
    assert enforce_project_sandbox("edit_file", {"edits": ["not a dict"]}, project) is None
    assert enforce_project_sandbox("edit_file", {"edits": [{}]}, project) is None


def test_run_code_directory_defaults_to_project_root(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"code": "print(1)"}
    assert enforce_project_sandbox("run_code", args, project) is None
    assert args["directory"] == str((tmp_path / "myproject").resolve())


def test_run_code_directory_outside_project_is_rejected(tmp_path):
    project = _project(tmp_path)
    args: dict[str, object] = {"code": "print(1)", "directory": str(tmp_path)}
    error = enforce_project_sandbox("run_code", args, project)
    assert error is not None


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
