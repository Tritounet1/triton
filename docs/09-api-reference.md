# HTTP API

The API (`server.py`) is usable directly - `curl`, a script, another client - without going through the desktop app or the CLI. That's literally what the desktop app itself does: everything goes through this same API.

## Interactive documentation

Once the server is running (`uv run python3 server.py`, listening on `127.0.0.1:8000`):

- **`/docs`** - Swagger UI, routes grouped by category (Chat, Sessions, Projects, Orchestrator, Subagents, Background Tasks, MCP, Settings, Models, Logs, Health), with each request/response schema and a "Try it out" button to call a route straight from the browser.
- **`/redoc`** - a read-only alternative, different layout.
- **`/openapi.json`** - the raw schema, useful for generating a client in another language.
- Visiting `/` (the root) redirects automatically to `/docs`.

## Things to know before calling it directly

- **`POST /chat` streams its response (Server-Sent Events)**, not plain JSON - each `event: ...\ndata: ...` in the stream corresponds to a piece of the reply (`token`, `tool_call`, `confirmation_required`, `session`, `title`, `error`...). Every other route responds with normal JSON.
- **No authentication** - the API only listens on `127.0.0.1` (localhost), built for local personal use, not for being exposed on a network.
- **`session_id` is optional** on the first `POST /chat` call (a conversation is created automatically) but has to be reused afterward to continue the same conversation - the API never "guesses" the last active conversation, unlike the CLI.
- A tool call that isn't read-only triggers a `confirmation_required` event in the stream and **blocks the reply for up to 5 minutes** waiting on `POST /chat/confirm` with the received `confirmation_id` - a script calling `/chat` needs to be ready to handle that (or avoid write tools by pre-approving them through a conversation that already clicked "always allow").

## Minimal example (`curl`)

```bash
# new conversation, first message
curl -N -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "hello"}'
# -> the SSE stream includes a "session" event with the session_id to reuse
```

See `/docs` for the full list and each route's detail - this page doesn't duplicate what Swagger already shows, it just calls out the pitfalls specific to this API (streaming, blocking confirmation) that an OpenAPI schema can't express on its own.
