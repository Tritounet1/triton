import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECTS_FILE = Path(__file__).parent / "projects.json"


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
