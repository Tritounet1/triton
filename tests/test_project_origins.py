import server
from triton.deployment import DeploymentProfile
from triton.storage import projects


def test_projects_are_scoped_to_the_active_deployment(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")
    projects.create_project("Local", "/tmp/local", project_id="desktop-project")
    projects.create_project(
        "Remote", "workspace://web-project", project_id="web-project", origin="web"
    )

    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.DESKTOP)
    assert [project.id for project in server.list_projects()] == ["desktop-project"]
    assert server._active_project("web-project") is None

    monkeypatch.setattr(server, "DEPLOYMENT_PROFILE", DeploymentProfile.WEB)
    assert [project.id for project in server.list_projects()] == ["web-project"]
    assert server._active_project("desktop-project") is None
