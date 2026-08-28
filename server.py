"""API HTTP pour Triton, pensée pour être consommée par l'app desktop Tauri
(app-desktop/). Réutilise telle quelle la logique du harness CLI (main.py,
api.py, tools.py, sessions.py, logs.py) ; seule la boucle de tool calling est
réécrite ici, parce que la confirmation avant un outil risqué ne peut pas
passer par un simple input() bloquant côté terminal : elle doit mettre le
flux SSE en pause et attendre un appel séparé du client (/chat/confirm).

Lancer en local : `uv run server.py` (ou `uv run uvicorn server:app --reload`).
L'API n'écoute que sur 127.0.0.1, jamais exposée au réseau.
"""

import json
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from api import MODEL, ChatResult, call_chat
from logs import log_event
from main import (
    MAX_ITERATIONS,
    SYSTEM_PROMPT,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
)
from sessions import (
    SESSIONS_DIR,
    delete_session,
    load_session,
    load_title,
    new_session_path,
    save_session,
    save_title,
)
from tools import TOOLS, TOOLS_REGISTRY

app = FastAPI(title="Triton API")

# tout tourne en local (127.0.0.1), donc pas de vrai enjeu de sécurité à
# restreindre les origines : la webview Tauri change d'origine entre le dev
# (http://localhost:1420) et le build (tauri://localhost, ou équivalent).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str


class ConfirmRequest(BaseModel):
    confirmation_id: str
    approved: bool


class RenameRequest(BaseModel):
    title: str


@dataclass
class PendingConfirmation:
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


PENDING_CONFIRMATIONS: dict[str, PendingConfirmation] = {}


def resolve_session(
    session_id: str | None,
) -> tuple[Path, list[ChatCompletionMessageParam], bool]:
    """Charge la session demandée si elle existe, sinon en crée une nouvelle.
    Contrairement au CLI, l'API ne reprend jamais silencieusement "la
    dernière session" : c'est au client de se souvenir de son session_id.
    Le booléen indique si la session vient d'être créée (utile pour savoir
    s'il faut générer un titre)."""
    if session_id:
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            return path, load_session(path), False

    path = new_session_path()
    return path, [{"role": "system", "content": SYSTEM_PROMPT}], True


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


MAX_TITLE_CHARS = 60


def generate_conversation_title(first_message: str) -> str:
    """Titre très court généré à partir du tout premier message d'une
    conversation, pour l'affichage cote client uniquement (jamais renvoyé
    au modèle par la suite).

    Le message est présenté comme une citation à résumer, pas envoyé tel
    quel en tour "user" : sinon le modèle a tendance à y répondre
    directement (ex. une question type "explique moi X" se fait traiter
    comme une vraie question) au lieu de produire un titre."""
    request: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": "tu résumes des messages en un titre très court (4 mots maximum), en "
            "français, sans guillemets, sans point final, sans emoji. tu ne réponds jamais "
            "à la question posée dans le message, tu donnes uniquement un titre qui la résume.",
        },
        {
            "role": "user",
            "content": f'donne un titre très court pour la conversation qui commence par ce '
            f'message :\n\n"{first_message}"',
        },
    ]
    result = call_chat(request)
    title = (result.content or "nouvelle conversation").strip().strip('"')
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1].rstrip() + "…"
    return title


def run_chat_stream(
    session_path: Path,
    messages: list[ChatCompletionMessageParam],
    first_message: str | None = None,
) -> Iterator[str]:
    yield sse("session", {"session_id": session_path.stem})

    if first_message is not None:
        title = generate_conversation_title(first_message)
        save_title(session_path.stem, title)
        yield sse("title", {"title": title})

    compressed, compress_message = compress_history_if_needed(messages)
    messages[:] = compressed
    if compress_message:
        yield sse("info", {"message": compress_message})

    iteration = 0
    done = False

    while iteration < MAX_ITERATIONS and not done:
        iteration += 1
        content_parts: list[str] = []
        reply: ChatResult | None = None

        for event in timed_stream_chat(messages, tools=TOOLS):
            if isinstance(event, str):
                content_parts.append(event)
                yield sse("token", {"text": event})
            else:
                reply = event

        assert reply is not None

        if reply.tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": to_tool_call_params(reply.tool_calls),
                }
            )

            for tool_call in reply.tool_calls:
                if tool_call.type != "function":
                    continue

                name = tool_call.function.name
                duration = 0.0

                try:
                    args = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    result = f"erreur : arguments invalides ({tool_call.function.arguments})"
                    args = {}
                else:
                    tool = TOOLS_REGISTRY.get(name)

                    if tool is None:
                        result = f"outil inconnu : {name}"
                    elif tool.read_only:
                        result = tool.fn(**args)
                    else:
                        confirmation_id = str(uuid.uuid4())
                        pending = PendingConfirmation()
                        PENDING_CONFIRMATIONS[confirmation_id] = pending

                        yield sse(
                            "confirmation_required",
                            {"confirmation_id": confirmation_id, "tool": name, "args": args},
                        )

                        got_response = pending.event.wait(timeout=300)
                        PENDING_CONFIRMATIONS.pop(confirmation_id, None)

                        if got_response and pending.approved:
                            result = tool.fn(**args)
                        else:
                            result = "action refusée par l'utilisateur"

                yield sse("tool_call", {"tool": name, "args": args, "result": result})

                log_event(
                    type="tool_call",
                    tool=name,
                    args=args,
                    result_preview=result[:300],
                    result_chars=len(result),
                    duration_seconds=round(duration, 3),
                )

                messages.append(
                    {"role": "tool", "tool_call_id": tool_call.id, "content": result}
                )

            continue

        if reply.content is None:
            yield sse("error", {"message": "le modèle n'a renvoyé ni texte ni appel d'outil."})
            done = True
            continue

        messages.append({"role": "assistant", "content": reply.content})
        yield sse(
            "done",
            {
                "content": reply.content,
                "model": reply.model,
                "prompt_tokens": reply.prompt_tokens,
                "completion_tokens": reply.completion_tokens,
                "total_tokens": reply.total_tokens,
            },
        )
        done = True

    if not done:
        yield sse("error", {"message": f"limite de {MAX_ITERATIONS} itérations atteinte."})

    save_session(session_path, messages)


@app.get("/health")
def health() -> dict[str, bool | str]:
    return {"ok": True, "model": MODEL}


@app.post("/chat")
def chat(body: ChatRequest) -> StreamingResponse:
    session_path, messages, is_new = resolve_session(body.session_id)
    messages.append({"role": "user", "content": body.message})

    return StreamingResponse(
        run_chat_stream(
            session_path, messages, first_message=body.message if is_new else None
        ),
        media_type="text/event-stream",
    )


@app.post("/chat/confirm")
def confirm(body: ConfirmRequest) -> dict[str, bool]:
    pending = PENDING_CONFIRMATIONS.get(body.confirmation_id)
    if pending is None:
        raise HTTPException(404, "confirmation inconnue ou déjà traitée")

    pending.approved = body.approved
    pending.event.set()
    return {"ok": True}


@app.get("/sessions")
def list_sessions() -> list[dict[str, str | None]]:
    if not SESSIONS_DIR.exists():
        return []
    ids = sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))
    return [{"id": session_id, "title": load_title(session_id)} for session_id in ids]


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> list[ChatCompletionMessageParam]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session introuvable")
    return load_session(path)


@app.put("/sessions/{session_id}/title")
def rename_session(session_id: str, body: RenameRequest) -> dict[str, bool]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session introuvable")
    save_title(session_id, body.title)
    return {"ok": True}


@app.delete("/sessions/{session_id}")
def remove_session(session_id: str) -> dict[str, bool]:
    if not delete_session(session_id):
        raise HTTPException(404, "session introuvable")
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
