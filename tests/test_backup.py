"""build_backup_zip (triton/backup.py) and GET /backup/export
(server.py): a single zip of everything the harness manages under
ROOT_DIR - see the module's own docstring for the full file/directory
list and why API keys are included as-is rather than redacted."""

import zipfile
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

import server
from triton import backup


@pytest.fixture(autouse=True)
def _isolated_root(tmp_path, monkeypatch):
    monkeypatch.setattr(backup, "ROOT_DIR", tmp_path)


@pytest.fixture
def client():
    return TestClient(server.app)


def test_build_backup_zip_includes_top_level_files(tmp_path):
    (tmp_path / "projects.json").write_text('[{"id": "p1"}]')
    (tmp_path / "settings.json").write_text('{"openrouter_api_key": "sk-secret"}')
    (tmp_path / ".env").write_text("OPEN_ROUTER_API_KEY=sk-also-secret\n")

    data = backup.build_backup_zip()

    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = zf.namelist()
        assert "projects.json" in names
        assert "settings.json" in names
        assert ".env" in names
        # API keys are included as-is, not redacted - see the module docstring
        assert zf.read("settings.json") == b'{"openrouter_api_key": "sk-secret"}'
        assert b"sk-also-secret" in zf.read(".env")


def test_build_backup_zip_includes_directories_recursively(tmp_path):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    (sessions_dir / "2026-01-01_120000.json").write_text("[]")
    project_memory_dir = tmp_path / "project_memory"
    project_memory_dir.mkdir()
    (project_memory_dir / "proj1.md").write_text("- a fact")

    data = backup.build_backup_zip()

    with zipfile.ZipFile(BytesIO(data)) as zf:
        names = zf.namelist()
        assert "sessions/2026-01-01_120000.json" in names
        assert "project_memory/proj1.md" in names


def test_build_backup_zip_never_includes_the_keychain_fallback_file(tmp_path):
    # secrets.json (triton.storage.keychain.FALLBACK_FILE, used on
    # platforms without a real OS keychain) holds MCP server secrets in
    # the clear - must never end up in an exportable zip, see the
    # module-level assert in backup.py.
    (tmp_path / "secrets.json").write_text('{"mcp:server:token": "sk-secret"}')
    (tmp_path / "projects.json").write_text('[{"id": "p1"}]')

    data = backup.build_backup_zip()

    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert "secrets.json" not in zf.namelist()
        assert "projects.json" in zf.namelist()


def test_build_backup_zip_skips_missing_files_and_dirs(tmp_path):
    # nothing exists under ROOT_DIR at all - a fresh install
    data = backup.build_backup_zip()

    with zipfile.ZipFile(BytesIO(data)) as zf:
        assert zf.namelist() == []


def test_export_backup_endpoint(tmp_path, client):
    (tmp_path / "projects.json").write_text('[{"id": "p1"}]')

    r = client.get("/backup/export")

    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    disposition = r.headers["content-disposition"]
    assert disposition.startswith("attachment; filename=")
    assert disposition.endswith('.zip"')
    assert "triton-backup-" in disposition

    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        assert "projects.json" in zf.namelist()
