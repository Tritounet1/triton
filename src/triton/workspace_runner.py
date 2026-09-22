import os
import re
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

WORKSPACE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
WORKSPACES_DIR = Path(os.getenv("TRITON_WORKSPACES_DIR", "/workspaces"))
WORKSPACE_TOKEN = os.getenv("TRITON_WORKSPACE_TOKEN", "")

app = FastAPI(title="Triton Workspace Runner", docs_url=None, redoc_url=None)


class WorkspaceCreateRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=64)


def _require_token(token: str | None) -> None:
    if not WORKSPACE_TOKEN or token != WORKSPACE_TOKEN:
        raise HTTPException(401, "workspace authentication failed")


def _workspace_path(workspace_id: str) -> Path:
    if not WORKSPACE_ID_PATTERN.fullmatch(workspace_id):
        raise HTTPException(400, "invalid workspace id")
    return WORKSPACES_DIR / workspace_id


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/workspaces")
def create_workspace(
    body: WorkspaceCreateRequest,
    x_triton_workspace_token: str | None = Header(default=None),
) -> dict[str, str]:
    _require_token(x_triton_workspace_token)
    workspace = _workspace_path(body.workspace_id)
    if workspace.exists():
        raise HTTPException(409, "workspace already exists")
    workspace.mkdir(parents=True)
    return {"id": body.workspace_id}
