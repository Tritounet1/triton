import datetime
import json
from pathlib import Path
from typing import cast

from openai.types.chat import ChatCompletionMessageParam

SESSIONS_DIR = Path(__file__).parent / "sessions"


def latest_session_path() -> Path | None:
    """Renvoie le fichier de session le plus récent, s'il en existe un."""
    if not SESSIONS_DIR.exists():
        return None
    files = sorted(SESSIONS_DIR.glob("*.json"))
    return files[-1] if files else None


def new_session_path() -> Path:
    """Crée un identifiant de session basé sur la date, pour permettre un jour
    de gérer plusieurs conversations séparées plutôt qu'une seule mémoire globale."""
    SESSIONS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return SESSIONS_DIR / f"{timestamp}.json"


def load_session(path: Path) -> list[ChatCompletionMessageParam]:
    return cast(list[ChatCompletionMessageParam], json.loads(path.read_text()))


def save_session(path: Path, messages: list[ChatCompletionMessageParam]) -> None:
    path.write_text(json.dumps(messages, ensure_ascii=False, indent=2))


def title_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.title.txt"


def load_title(session_id: str) -> str | None:
    """Titre choisi par l'utilisateur ou généré au premier message. Stocké à
    part de l'historique (fichier séparé) : ça reste une info d'affichage
    côté client, jamais renvoyée au modèle, et ça ne touche pas au format
    de session.json que le CLI lit/écrit aussi."""
    path = title_path(session_id)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def save_title(session_id: str, title: str) -> None:
    SESSIONS_DIR.mkdir(exist_ok=True)
    title_path(session_id).write_text(title.strip())
