import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from openai.types.chat import ChatCompletionToolParam


@dataclass
class Tool:
    schema: ChatCompletionToolParam
    fn: Callable[..., str]
    read_only: bool


def read_file(path: str) -> str:
    try:
        return Path(path).read_text()
    except OSError as e:
        return f"erreur : impossible de lire {path} ({e})"


def list_files(directory: str = ".") -> str:
    try:
        entries = sorted(Path(directory).iterdir())
    except OSError as e:
        return f"erreur : impossible de lister {directory} ({e})"
    if not entries:
        return "(dossier vide)"
    return "\n".join(f"{'d' if p.is_dir() else 'f'} {p.name}" for p in entries)


def write_file(path: str, content: str) -> str:
    try:
        Path(path).write_text(content)
    except OSError as e:
        return f"erreur : impossible d'écrire {path} ({e})"
    return f"fichier {path} écrit ({len(content)} caractères)"


def run_shell(command: str) -> str:
    # pas de confirmation avant execution pour l'instant, ca vient a l'etape 7
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "erreur : commande trop longue (timeout 10s)"
    output = (result.stdout + result.stderr).strip()
    return output or f"(pas de sortie, code {result.returncode})"


TOOLS_REGISTRY: dict[str, Tool] = {
    "read_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Lit et retourne le contenu d'un fichier texte.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Chemin du fichier à lire.",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        fn=read_file,
        read_only=True,
    ),
    "list_files": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "list_files",
                "description": "Liste les fichiers et dossiers d'un répertoire.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "directory": {
                            "type": "string",
                            "description": "Chemin du dossier à lister (défaut : dossier courant).",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=list_files,
        read_only=True,
    ),
    "write_file": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Écrit du contenu dans un fichier texte (écrase s'il existe déjà).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Chemin du fichier à écrire.",
                        },
                        "content": {
                            "type": "string",
                            "description": "Contenu à écrire dans le fichier.",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        fn=write_file,
        read_only=False,
    ),
    "run_shell": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "run_shell",
                "description": "Exécute une commande shell et retourne sa sortie.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Commande shell à exécuter.",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        fn=run_shell,
        read_only=False,
    ),
}

TOOLS: list[ChatCompletionToolParam] = [tool.schema for tool in TOOLS_REGISTRY.values()]


def rebuild_tools_list() -> None:
    """Recalcule TOOLS a partir de TOOLS_REGISTRY, en mutant la liste en place
    (jamais de reassignation) : main.py et server.py ont fait `from tools
    import TOOLS` et gardent donc une reference vers ce meme objet liste, une
    reassignation ne serait pas vue par ces modules. Appele par mcp_client.py
    a chaque connexion/deconnexion d'un serveur MCP, pour que les outils
    distants apparaissent/disparaissent sans changement cote main.py/server.py."""
    TOOLS.clear()
    TOOLS.extend(tool.schema for tool in TOOLS_REGISTRY.values())
