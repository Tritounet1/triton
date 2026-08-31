import datetime
import json
from pathlib import Path
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

from triton.paths import ROOT_DIR

SESSIONS_DIR = ROOT_DIR / "sessions"


def latest_session_path() -> Path | None:
    """Returns the most recent session file, if one exists."""
    if not SESSIONS_DIR.exists():
        return None
    files = sorted(SESSIONS_DIR.glob("*.json"))
    return files[-1] if files else None


def new_session_path() -> Path:
    """Creates a session id based on the date, to allow one day handling
    multiple separate conversations rather than a single global memory."""
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return SESSIONS_DIR / f"{timestamp}.json"


def load_session(path: Path) -> list[ChatCompletionMessageParam]:
    return cast(list[ChatCompletionMessageParam], json.loads(path.read_text()))


def save_session(path: Path, messages: list[ChatCompletionMessageParam]) -> None:
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2))


def title_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.title.txt"


def load_title(session_id: str) -> str | None:
    """Title chosen by the user or generated on the first message. Stored
    separately from the history (its own file): it stays a client-side
    display detail, never sent back to the model, and doesn't touch the
    session.json format that the CLI also reads/writes."""
    path = title_path(session_id)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def save_title(session_id: str, title: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    title_path(session_id).write_text(title.strip())


def permissions_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.permissions.json"


def load_always_allowed(session_id: str) -> set[str]:
    """Tools the user chose to allow without reconfirmation, for THIS
    conversation only (the "always allow" button on the confirmation
    prompt). Stored separately from the history, like the title: a new
    conversation starts with a clean confirmation state."""
    path = permissions_path(session_id)
    if not path.exists():
        return set()
    return set(json.loads(path.read_text()))


def allow_always(session_id: str, tool_name: str) -> None:
    names = load_always_allowed(session_id)
    names.add(tool_name)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    permissions_path(session_id).write_text(json.dumps(sorted(names), ensure_ascii=False, indent=2))


def project_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.project.txt"


def load_session_project(session_id: str) -> str | None:
    """Id of the project this conversation belongs to, if any. Stored
    separately from the history, like the title and permissions: a
    conversation started outside a project has no such file."""
    path = project_path(session_id)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def save_session_project(session_id: str, project_id: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    project_path(session_id).write_text(project_id.strip())


def clear_session_project(session_id: str) -> None:
    project_path(session_id).unlink(missing_ok=True)


def pinned_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.pinned"


def is_pinned(session_id: str) -> bool:
    """A conversation is pinned purely by this marker file's presence - no
    content to read, like a boolean flag stored as a filesystem fact
    rather than a line inside it."""
    return pinned_path(session_id).exists()


def set_pinned(session_id: str, pinned: bool) -> None:
    if pinned:
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        pinned_path(session_id).touch()
    else:
        pinned_path(session_id).unlink(missing_ok=True)


def model_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.model.txt"


def load_session_model(session_id: str) -> str | None:
    """Model override for THIS conversation only (set via the /model
    command - see server.py's PUT /sessions/{id}/model), taking priority
    over the global default (settings.json) for every turn in this
    session. Stored separately from the history, like the title/project:
    a conversation with no override has no such file."""
    path = model_path(session_id)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def save_session_model(session_id: str, model: str) -> None:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    model_path(session_id).write_text(model.strip())


def session_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.json"


def delete_session(session_id: str) -> bool:
    """Deletes a conversation (history + title + permissions + project
    link + pin + model override). Returns False if it didn't exist."""
    path = session_path(session_id)
    if not path.exists():
        return False
    path.unlink()
    title_path(session_id).unlink(missing_ok=True)
    permissions_path(session_id).unlink(missing_ok=True)
    pinned_path(session_id).unlink(missing_ok=True)
    model_path(session_id).unlink(missing_ok=True)
    clear_session_project(session_id)
    return True
