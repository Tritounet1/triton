# Triton

Triton is a Python AI-agent harness built to understand how tools such as Claude Code and
Claude Desktop work: an LLM decides what to do, while the harness supplies context, tools,
permissions, persistence, and the execution loop.

![Triton desktop chat](docs/assets/images/homescreen.png)

## What it does

- Streams multi-turn conversations through OpenRouter-compatible models.
- Runs a ReAct-style loop: the model can call tools, inspect their results, and continue until
  it produces a final answer.
- Manages files, search, Git, shell commands, tests, web search, memories, todos, background
  tasks, snapshots, and MCP tools.
- Stores conversations, logs, settings, and project state locally or in persistent Docker
  volumes.
- Provides the same client experience in three forms: terminal, native desktop app, and a
  self-hosted web app.

## Interfaces

| Interface | Use case | Start command |
| --- | --- | --- |
| CLI | Local agent from a terminal | `uv run main.py` |
| Desktop | Tauri + React client for local work | `pnpm tauri dev` in `app-desktop/` |
| Web | Self-hosted browser client with isolated workspaces | `docker compose up --build -d` |

The CLI and FastAPI server use the same agent loop. The React client is shared by the desktop
and web builds; Tauri-only capabilities are hidden when running in a browser.

## Quick start

Requirements: Python 3.13 and [uv](https://docs.astral.sh/uv/). The desktop client also needs
Node.js and pnpm.

```sh
git clone <repository-url>
cd harness
uv sync
cp .env.template .env
# Add OPEN_ROUTER_API_KEY to .env
uv run main.py
```

Run the API for the desktop client in a second terminal:

```sh
uv run server.py
```

Then start the desktop client:

```sh
cd app-desktop
pnpm install
pnpm tauri dev
```

## Self-hosted web app

The Compose stack builds the React client, serves FastAPI, and starts a separate workspace
runner. The runner has no published port and has its own persistent volume; project files,
shell commands, background tasks, MCP servers, and subagents run there instead of on the host.

```sh
cp .env.example .env
# Set OPEN_ROUTER_API_KEY, TRITON_WEB_PASSWORD,
# TRITON_WEB_SESSION_SECRET, and TRITON_WORKSPACE_TOKEN.
# Set TRITON_WEB_SECURE_COOKIES=false only for local HTTP testing.
docker compose up --build -d
```

Open `http://127.0.0.1:8000`. For a VPS or Dokploy deployment, connect this service to your
own HTTPS setup and keep `TRITON_WEB_SECURE_COOKIES=true`. The full deployment, backup, and
observability guide is in [docs/08-web-deployment.md](docs/08-web-deployment.md).

## Architecture

```text
main.py / server.py
        │
        ├── src/triton/llm/       model calls and shared chat loop
        ├── src/triton/tools/     local, web, project, Git, process, and MCP tools
        ├── src/triton/agents/    subagents and orchestration
        └── src/triton/storage/   sessions, projects, settings, and logs

app-desktop/                     React client and Tauri desktop shell
workspace/                       isolated runner used by the web profile
```

`server.py` streams events with Server-Sent Events and pauses for confirmation before
modifying actions. In the web profile, tools that act on a project are forwarded to the
workspace runner over a private, token-protected Docker network.

## Development

```sh
uv run pytest
uv run pre-commit run --all-files

cd app-desktop
pnpm lint
pnpm test
pnpm build
```

`pre-commit` runs Ruff, basedpyright, pytest, ESLint, and TypeScript checks on relevant files
before each commit.

## Packaging the desktop app

Release builds bundle the FastAPI server as a Tauri sidecar, so the user does not need Python
or uv installed separately:

```sh
./packaging/build_server.sh
cd app-desktop
pnpm tauri build
```

Build on the target operating system. The packaged app stores its data in the operating system's
standard application-data directory; add an `.env` file with `OPEN_ROUTER_API_KEY` there before
making model calls.
