"""GET /projects/{id}/tree used to be able to show only framework
build/cache directories (.next, .pnpm-store, ...) and nothing else: they
weren't in SKIP_DIR_NAMES, sorted before real source dirs/files
alphabetically (dot-prefixed, and _build_tree walks depth-first), and
could easily contain thousands of generated files each - enough on their
own to exhaust MAX_TREE_ENTRIES before the walk ever reached src/,
package.json, etc. Found via a real Next.js project scaffolded through
Triton itself, where the file panel ended up showing only .next/
.pnpm-store next to a "certains fichiers ne sont pas affichés" notice."""

import pytest
from fastapi.testclient import TestClient

import server
from triton.storage import projects


@pytest.fixture(autouse=True)
def _isolated_projects_file(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_FILE", tmp_path / "projects.json")


@pytest.fixture
def client():
    return TestClient(server.app)


def _project(tmp_path):
    folder = tmp_path / "myproject"
    folder.mkdir()
    return projects.create_project("test-project", str(folder))


def _names(entries: list[dict]) -> set[str]:
    return {e["name"] for e in entries}


def test_next_and_pnpm_store_caches_dont_starve_the_budget(tmp_path, client, monkeypatch):
    project = _project(tmp_path)
    root = tmp_path / "myproject"

    # a small budget makes the regression reproducible without actually
    # writing thousands of files
    monkeypatch.setattr(server, "MAX_TREE_ENTRIES", 10)

    next_cache = root / ".next" / "cache"
    next_cache.mkdir(parents=True)
    for i in range(50):
        (next_cache / f"chunk-{i}.js").write_text("x")

    pnpm_store = root / ".pnpm-store"
    pnpm_store.mkdir()
    for i in range(50):
        (pnpm_store / f"pkg-{i}").write_text("x")

    (root / "package.json").write_text("{}")
    (root / "src").mkdir()
    (root / "src" / "index.ts").write_text("export {}")

    r = client.get(f"/projects/{project.id}/tree")

    assert r.status_code == 200
    body = r.json()
    assert body["truncated"] is False
    top_level = _names(body["tree"])
    assert ".next" not in top_level
    assert ".pnpm-store" not in top_level
    assert "package.json" in top_level
    assert "src" in top_level
