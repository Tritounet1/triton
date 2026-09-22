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


def test_workspace_runner_lists_and_serves_workspace_files(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    (workspace / "notes").mkdir(parents=True)
    (workspace / "notes" / "readme.md").write_text("# Triton")

    with TestClient(workspace_runner.app) as client:
        tree = client.get(
            "/workspaces/project-a/tree",
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )
        file = client.get(
            "/workspaces/project-a/file",
            params={"path": "notes/readme.md"},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )
        escaped = client.get(
            "/workspaces/project-a/file",
            params={"path": "../outside"},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )

    assert tree.json() == {
        "tree": [
            {
                "name": "notes",
                "path": "notes",
                "is_dir": True,
                "children": [{"name": "readme.md", "path": "notes/readme.md", "is_dir": False}],
            }
        ],
        "truncated": False,
    }
    assert file.text == "# Triton"
    assert escaped.status_code == 403


def test_workspace_runner_deletes_a_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    (workspace / "nested").mkdir(parents=True)
    (workspace / "nested" / "file.txt").write_text("content")

    with TestClient(workspace_runner.app) as client:
        response = client.delete(
            "/workspaces/project-a",
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )

    assert response.json() == {"ok": True}
    assert not workspace.exists()


def test_workspace_runner_executes_tools_inside_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    workspace.mkdir()

    with TestClient(workspace_runner.app) as client:
        write = client.post(
            "/workspaces/project-a/tools",
            json={"name": "write_file", "args": {"path": "notes/readme.md", "content": "Triton"}},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )
        edit = client.post(
            "/workspaces/project-a/tools",
            json={
                "name": "edit_file",
                "args": {
                    "edits": [
                        {"path": "notes/readme.md", "old_string": "Triton", "new_string": "Harness"}
                    ]
                },
            },
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )
        command = client.post(
            "/workspaces/project-a/tools",
            json={"name": "run_shell", "args": {"command": "cat notes/readme.md"}},
            headers={"X-Triton-Workspace-Token": "workspace-token"},
        )

    assert write.json()["result"] == "file notes/readme.md written (6 characters)"
    assert edit.json()["result"] == "notes/readme.md: 1 edit(s) applied"
    assert command.json() == {"result": "Harness"}
