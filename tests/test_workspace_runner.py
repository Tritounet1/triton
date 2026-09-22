import json
import subprocess
import time

from fastapi.testclient import TestClient

from triton import workspace_runner

TOKEN_HEADER = {"X-Triton-Workspace-Token": "workspace-token"}


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


def _setup_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "TASKS_DIR", tmp_path / ".tasks")
    monkeypatch.setattr(workspace_runner, "SNAPSHOTS_DIR", tmp_path / ".snapshots")
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    (tmp_path / "project-a").mkdir()


def test_workspace_runner_starts_lists_and_reads_a_task(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        started = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "echo hi", "name": "greet"},
            headers=TOKEN_HEADER,
        )
        task_id = started.json()["id"]
        listed = client.get(
            "/workspaces/project-a/tasks",
            params={"session_id": "session-1"},
            headers=TOKEN_HEADER,
        )
        detail = None
        for _ in range(50):
            detail = client.get(f"/workspaces/project-a/tasks/{task_id}", headers=TOKEN_HEADER)
            if detail.json()["logs"]:
                break
            time.sleep(0.1)

    assert started.status_code == 200
    assert started.json()["workspace_id"] == "project-a"
    assert started.json()["session_id"] == "session-1"
    assert started.json()["name"] == "greet"
    assert [t["id"] for t in listed.json()] == [task_id]
    assert detail is not None
    assert "hi" in detail.json()["logs"]


def test_workspace_runner_list_tasks_filters_by_session(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-2", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        listed = client.get(
            "/workspaces/project-a/tasks",
            params={"session_id": "session-1"},
            headers=TOKEN_HEADER,
        )

    assert len(listed.json()) == 1
    assert listed.json()[0]["session_id"] == "session-1"


def test_workspace_runner_stops_a_task_without_bloating_persisted_state(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        started = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        task_id = started.json()["id"]
        stopped = client.post(f"/workspaces/project-a/tasks/{task_id}/stop", headers=TOKEN_HEADER)

    assert stopped.json()["status"] == "stopped"
    persisted = json.loads((tmp_path / ".tasks" / f"{task_id}.json").read_text())
    assert "logs" not in persisted


def test_workspace_runner_deletes_a_stopped_task_but_not_a_running_one(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        started = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        task_id = started.json()["id"]
        denied = client.delete(f"/workspaces/project-a/tasks/{task_id}", headers=TOKEN_HEADER)
        client.post(f"/workspaces/project-a/tasks/{task_id}/stop", headers=TOKEN_HEADER)
        allowed = client.delete(f"/workspaces/project-a/tasks/{task_id}", headers=TOKEN_HEADER)

    assert denied.status_code == 409
    assert allowed.json() == {"deleted": True}
    assert not (tmp_path / ".tasks" / f"{task_id}.json").exists()


def test_workspace_runner_greps_and_globs_inside_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    (workspace / "src").mkdir(parents=True)
    (workspace / "src" / "main.py").write_text("def hello():\n    return 'hi'\n")
    (workspace / "notes.md").write_text("hello there")
    (workspace / "node_modules").mkdir()
    (workspace / "node_modules" / "ignored.py").write_text("hello")

    with TestClient(workspace_runner.app) as client:
        grep = client.post(
            "/workspaces/project-a/tools",
            json={"name": "grep", "args": {"pattern": "hello"}},
            headers=TOKEN_HEADER,
        )
        glob = client.post(
            "/workspaces/project-a/tools",
            json={"name": "glob", "args": {"pattern": "**/*.py"}},
            headers=TOKEN_HEADER,
        )

    assert "notes.md:1:hello there" in grep.json()["result"]
    assert "node_modules" not in grep.json()["result"]
    assert glob.json()["result"] == "src/main.py"


def test_workspace_runner_runs_git_commands_inside_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.c"], cwd=workspace, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=workspace, check=True)
    (workspace / "readme.md").write_text("Triton")

    with TestClient(workspace_runner.app) as client:
        status_before = client.post(
            "/workspaces/project-a/tools",
            json={"name": "git_status", "args": {}},
            headers=TOKEN_HEADER,
        )
        commit = client.post(
            "/workspaces/project-a/tools",
            json={"name": "git_commit", "args": {"message": "initial"}},
            headers=TOKEN_HEADER,
        )
        log = client.post(
            "/workspaces/project-a/tools",
            json={"name": "git_log", "args": {}},
            headers=TOKEN_HEADER,
        )

    assert "readme.md" in status_before.json()["result"]
    assert "initial" in commit.json()["result"]
    assert "initial" in log.json()["result"]


def test_workspace_runner_runs_tests_and_code_inside_its_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_runner, "WORKSPACES_DIR", tmp_path)
    monkeypatch.setattr(workspace_runner, "WORKSPACE_TOKEN", "workspace-token")
    workspace = tmp_path / "project-a"
    workspace.mkdir()
    (workspace / "test_ok.py").write_text("def test_ok():\n    assert True\n")

    with TestClient(workspace_runner.app) as client:
        tests = client.post(
            "/workspaces/project-a/tools",
            json={"name": "run_tests", "args": {}},
            headers=TOKEN_HEADER,
        )
        code = client.post(
            "/workspaces/project-a/tools",
            json={"name": "run_code", "args": {"code": "print(1 + 1)"}},
            headers=TOKEN_HEADER,
        )

    assert "1 passed" in tests.json()["result"]
    assert code.json()["result"] == "2"


def test_workspace_runner_caps_concurrent_tasks(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_runner, "MAX_CONCURRENT_TASKS", 1)

    with TestClient(workspace_runner.app) as client:
        first = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        second = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_workspace_runner_takes_a_snapshot_once_per_turn(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    (tmp_path / "project-a" / "readme.md").write_text("v1")

    with TestClient(workspace_runner.app) as client:
        first = client.post(
            "/workspaces/project-a/snapshots",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )
        second = client.post(
            "/workspaces/project-a/snapshots",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )
        listed = client.get(
            "/workspaces/project-a/snapshots",
            params={"session_id": "session-1"},
            headers=TOKEN_HEADER,
        )

    assert first.json() == {"taken": True}
    assert second.json() == {"taken": False}
    points = listed.json()
    assert [p["turn_index"] for p in points] == [1]
    assert points[0]["created_at"]


def test_workspace_runner_restores_a_snapshot(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    workspace = tmp_path / "project-a"
    (workspace / "readme.md").write_text("v1")

    with TestClient(workspace_runner.app) as client:
        client.post(
            "/workspaces/project-a/snapshots",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )
        (workspace / "readme.md").write_text("v2")
        (workspace / "new.txt").write_text("created after the snapshot")
        restored = client.post(
            "/workspaces/project-a/snapshots/restore",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )

    assert restored.json() == {"restored": True}
    assert (workspace / "readme.md").read_text() == "v1"
    assert not (workspace / "new.txt").exists()


def test_workspace_runner_restoring_an_unknown_turn_is_a_404(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        restored = client.post(
            "/workspaces/project-a/snapshots/restore",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )

    assert restored.status_code == 404


def test_workspace_runner_deletes_snapshots_with_the_workspace(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)

    with TestClient(workspace_runner.app) as client:
        client.post(
            "/workspaces/project-a/snapshots",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )
        client.delete("/workspaces/project-a", headers=TOKEN_HEADER)

    assert not (tmp_path / ".snapshots" / "project-a").exists()


def test_workspace_runner_caps_concurrent_tasks_per_workspace(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_runner, "MAX_CONCURRENT_TASKS_PER_WORKSPACE", 1)
    (tmp_path / "project-b").mkdir()

    with TestClient(workspace_runner.app) as client:
        first = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        second = client.post(
            "/workspaces/project-a/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )
        other_workspace = client.post(
            "/workspaces/project-b/tasks",
            json={"session_id": "session-1", "command": "sleep 5"},
            headers=TOKEN_HEADER,
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert other_workspace.status_code == 200


def test_workspace_runner_rejects_writes_over_its_disk_quota(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_runner, "MAX_WORKSPACE_BYTES", 10)

    with TestClient(workspace_runner.app) as client:
        write = client.post(
            "/workspaces/project-a/tools",
            json={"name": "write_file", "args": {"path": "big.txt", "content": "x" * 100}},
            headers=TOKEN_HEADER,
        )

    assert "quota" in write.json()["result"]
    assert not (tmp_path / "project-a" / "big.txt").exists()


def test_workspace_runner_maintenance_purges_orphaned_workspaces(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    (tmp_path / "project-orphan").mkdir()

    with TestClient(workspace_runner.app) as client:
        result = client.post(
            "/maintenance/purge",
            json={"keep_workspace_ids": ["project-a"]},
            headers=TOKEN_HEADER,
        )

    assert result.json()["orphaned_workspaces_removed"] == 1
    assert not (tmp_path / "project-orphan").exists()
    assert (tmp_path / "project-a").exists()


def test_workspace_runner_maintenance_purges_expired_snapshots(monkeypatch, tmp_path):
    _setup_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(workspace_runner, "SNAPSHOT_MAX_AGE_DAYS", -1)

    with TestClient(workspace_runner.app) as client:
        client.post(
            "/workspaces/project-a/snapshots",
            json={"session_id": "session-1", "turn_index": 1},
            headers=TOKEN_HEADER,
        )
        result = client.post(
            "/maintenance/purge",
            json={"keep_workspace_ids": ["project-a"]},
            headers=TOKEN_HEADER,
        )

    assert result.json()["expired_snapshots_removed"] == 1
    assert not (tmp_path / ".snapshots" / "project-a" / "session-1_1").exists()
