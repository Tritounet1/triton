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

from api import MODEL, ChatResult
from logs import log_event
from main import (
    MAX_ITERATIONS,
    SYSTEM_PROMPT,
    compress_history_if_needed,
    timed_stream_chat,
    to_tool_call_params,
)
from sessions import SESSIONS_DIR, load_session, new_session_path, save_session
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


@dataclass
class PendingConfirmation:
    event: threading.Event = field(default_factory=threading.Event)
    approved: bool = False


PENDING_CONFIRMATIONS: dict[str, PendingConfirmation] = {}


def resolve_session(session_id: str | None) -> tuple[Path, list[ChatCompletionMessageParam]]:
    """Charge la session demandée si elle existe, sinon en crée une nouvelle.
    Contrairement au CLI, l'API ne reprend jamais silencieusement "la
    dernière session" : c'est au client de se souvenir de son session_id."""
    if session_id:
        path = SESSIONS_DIR / f"{session_id}.json"
        if path.exists():
            return path, load_session(path)

    path = new_session_path()
    return path, [{"role": "system", "content": SYSTEM_PROMPT}]


def sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def run_chat_stream(
    session_path: Path, messages: list[ChatCompletionMessageParam]
) -> Iterator[str]:
    yield sse("session", {"session_id": session_path.stem})

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
    session_path, messages = resolve_session(body.session_id)
    messages.append({"role": "user", "content": body.message})

    return StreamingResponse(
        run_chat_stream(session_path, messages), media_type="text/event-stream"
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
def list_sessions() -> list[str]:
    if not SESSIONS_DIR.exists():
        return []
    return sorted(p.stem for p in SESSIONS_DIR.glob("*.json"))


@app.get("/sessions/{session_id}")
def get_session(session_id: str) -> list[ChatCompletionMessageParam]:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.exists():
        raise HTTPException(404, "session introuvable")
    return load_session(path)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
