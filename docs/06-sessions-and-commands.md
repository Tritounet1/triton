# Sessions and commands

## Managing a conversation

Each conversation (`storage/sessions.py`) is a `sessions/<id>.json` file (the raw history sent to/received from the model) accompanied by several optional sidecar files, following the same pattern - one file per facet, rather than one big central JSON object:

| Sidecar file | Role |
|---|---|
| `<id>.title.txt` | Displayed title (auto-generated on the first message, or renamed by hand) |
| `<id>.permissions.json` | Tools "always allowed" for this conversation (the confirmation prompt's button) |
| `<id>.project.txt` | Id of the linked project, if any |
| `<id>.pinned` | Pure presence marker (pinned or not - no content to read) |
| `<id>.model.txt` | Model override (`/model` command), takes priority over the global model |
| `<id>.memory.md` | This conversation's own memory (if no project - see [Memory](04-memory.md)) |

Actions available from the sidebar (the **⋯** menu on each row): rename, export (Markdown or JSON, `GET /sessions/{id}/export`), pin/unpin (pinned conversations sort to the top of their list), delete (also wipes every sidecar file above).

**Search** (`GET /sessions/search?q=...`) filters by title and message content, server-side - no round-tripping the full history just to filter it.

## `/` commands (composer)

Typed directly into the message field, triggered by the `/` character (Notion/Discord-style menu). Each is a shortcut to something that already exists server-side - not a new model capability.

| Command | Effect |
|---|---|
| `/multi-agents <task>` | Runs the multi-agent orchestrator (see [Multi-agent](05-multi-agent.md)) |
| `/model <query>` | Changes **this conversation's** model only - fuzzy-matches by substring against the id or name in the already-loaded OpenRouter catalog (`gpt-5` finds `openai/gpt-5`) |
| `/cost` | Shows a summary (calls, input/output tokens, estimated cost) of the current conversation |
| `/undo` | Triggers the write-tool safety net's restore (see [Projects and security](03-projects-and-security.md)), with confirmation |

## Per-conversation model override

`/model` doesn't change the global setting (Settings) - it just sets `sessions/<id>.model.txt`, which takes priority over the default model *for that conversation only* (see `stream_chat`/`timed_stream_chat` in `llm/`, which accept an optional `model` that overrides `get_model()`). The model badge shown in the composer, the "Triton is thinking" avatar, and attachment capabilities (whether images/PDFs are supported) all reflect this override, not the global model.

## Per-conversation cost

`/cost` (and the `GET /sessions/{id}/cost` endpoint) sums up log entries (`logs/events.jsonl`) of type `model_call` tagged with the conversation's `session_id` - a tag that didn't exist before this feature was added, so a conversation predating this change shows a cost of zero (nothing to retroactively attribute it to).

For a global view (every day, across all conversations), see the chart in `LogsSettings.tsx`'s settings page - no per-project breakdown yet.
