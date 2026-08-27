from collections.abc import Callable
from pathlib import Path

from openai.types.chat import ChatCompletionToolParam

TOOLS: list[ChatCompletionToolParam] = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Lit et retourne le contenu d'un fichier texte.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Chemin du fichier a lire, relatif au dossier courant.",
                    },
                },
                "required": ["path"],
            },
        },
    },
]


def read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as e:
        return f"erreur : impossible de lire {path} ({e})"


TOOL_FUNCTIONS: dict[str, Callable[..., str]] = {
    "read_file": read_file,
}
