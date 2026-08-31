"""GET /projects/{id}/file serves a project file's raw bytes for the
desktop app's in-app PDF/HTML/Markdown viewer - it takes a single free-form
path (not a tool call's args, so enforce_project_sandbox doesn't apply
directly), and has to reject a path outside the project folder by hand."""

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import projects


@pytest.fixture(autouse=True)
def _isolated_projects_file(tmp_path, monkeypatch):
    """Real projects.json is never touched: every test gets its own empty
    file, matching test_role_model_overrides.py's SETTINGS_FILE pattern."""
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


@pytest.fixture
def client():
    return TestClient(server.app)


def _project(tmp_path):
    folder = tmp_path / "myproject"
    folder.mkdir()
    return projects.create_project("test-project", str(folder))


def test_serves_a_file_inside_the_project(tmp_path, client):
    project = _project(tmp_path)
    (tmp_path / "myproject" / "notes.md").write_text("# hello")

    r = client.get(
        f"/projects/{project.id}/file", params={"path": str(tmp_path / "myproject" / "notes.md")}
    )
    assert r.status_code == 200
    assert r.text == "# hello"


def test_rejects_a_path_outside_the_project(tmp_path, client):
    project = _project(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("secret")

    r = client.get(f"/projects/{project.id}/file", params={"path": str(outside)})
    assert r.status_code == 403


def test_rejects_a_relative_path_escaping_via_dotdot(tmp_path, client):
    project = _project(tmp_path)
    (tmp_path / "elsewhere.txt").write_text("secret")

    r = client.get(
        f"/projects/{project.id}/file",
        params={"path": str(tmp_path / "myproject" / ".." / "elsewhere.txt")},
    )
    assert r.status_code == 403


def test_404_for_a_missing_file(tmp_path, client):
    project = _project(tmp_path)

    r = client.get(
        f"/projects/{project.id}/file",
        params={"path": str(tmp_path / "myproject" / "nope.txt")},
    )
    assert r.status_code == 404


def test_404_for_an_unknown_project(client):
    r = client.get("/projects/does-not-exist/file", params={"path": "/tmp/x"})
    assert r.status_code == 404
