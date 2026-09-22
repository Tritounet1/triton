from fastapi.testclient import TestClient

from triton import workspace_runner


def test_workspace_runner_requires_a_private_token(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")

    with TestClient(workspace_runner.app) as client:
        denied = client.post("/workspaces", json={"workspace_id": "project-a"})
        created = client.post(
            "/workspaces",
            json={"workspace_id": "project-a"},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )
        duplicate = client.post(
            "/workspaces",
            json={"workspace_id": "project-a"},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )

    assert denied.status_code == 401
    assert created.json() == {"id": "project-a"}
    assert (tmp_path / "project-a").is_dir()
    assert duplicate.status_code == 409


def test_workspace_runner_rejects_path_like_workspace_ids(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")

    with TestClient(workspace_runner.app) as client:
        response = client.post(
            "/workspaces",
            json={"workspace_id": "../outside"},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )

    assert response.status_code == 400
