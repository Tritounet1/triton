import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from triton.paths import ROOT_DIR

PROJECTS_FILE = ROOT_DIR / "projects.json"
# memory shared by every conversation belonging to the same project -
# current ones and any created later - unlike a project-less conversation,
# whose memory is private to it alone (see storage/sessions.py's
# load_session_memory/append_session_memory). Kept even if the project
# itself is later deleted, same as its conversations already are: deleting
# a project only unlinks them (see server.py's DELETE /projects/{id}), it
# doesn't erase them.
PROJECT_MEMORY_DIR = ROOT_DIR / "project_memory"


@dataclass
class Project:
    id: str
    name: str
    folder_path: str


def load_projects() -> list[Project]:
    if not PROJECTS_FILE.exists():
        return []
    raw = json.loads(PROJECTS_FILE.read_text())
    return [Project(**p) for p in raw]


def save_projects(projects: list[Project]) -> None:
    PROJECTS_FILE.write_text(
        json.dumps([asdict(p) for p in projects], ensure_ascii=False, indent=2)
    )


def get_project(project_id: str) -> Project | None:
    return next((p for p in load_projects() if p.id == project_id), None)


def create_project(name: str, folder_path: str) -> Project:
    projects = load_projects()
    project = Project(id=uuid.uuid4().hex, name=name, folder_path=folder_path)
    projects.append(project)
    save_projects(projects)
    return project


def rename_project(project_id: str, name: str) -> bool:
    projects = load_projects()
    found = False
    for p in projects:
        if p.id == project_id:
            p.name = name
            found = True
    if not found:
        return False
    save_projects(projects)
    return True


def delete_project(project_id: str) -> bool:
    projects = load_projects()
    remaining = [p for p in projects if p.id != project_id]
    if len(remaining) == len(projects):
        return False
    save_projects(remaining)
    return True


def project_memory_path(project_id: str) -> Path:
    return PROJECT_MEMORY_DIR / f"{project_id}.md"


def load_project_memory(project_id: str) -> str:
    path = project_memory_path(project_id)
    if not path.exists():
        return ""
    return path.read_text().strip()


def append_project_memory(project_id: str, note: str) -> None:
    PROJECT_MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    with project_memory_path(project_id).open("a", encoding="utf-8") as f:
        f.write(f"- {note.strip()}\n")
