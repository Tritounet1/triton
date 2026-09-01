# Chat and tools

## The flow of a conversation

1. The user sends a message (`POST /chat`, or directly in the CLI).
2. The model streams its reply - text appears token by token (SSE on the API side, direct rendering in the CLI).
3. If the model wants to act (read a file, write one, run a command...), it emits one or more **tool calls**. Each goes through the same path:
   - **Sandboxing** if the conversation is linked to a project (see [Projects and security](03-projects-and-security.md)).
   - **Confirmation** if the tool isn't read-only and hasn't already been approved "always" for this conversation - the app shows the tool, its arguments, and for `edit_file`/`write_file` a before/after diff preview (`EditFileDiff`/`WriteFileDiff` in `App.tsx`).
   - **Execution**, then the result is handed back to the model, which continues.
4. The turn ends when the model replies with plain text (no tool call).

A conversation can also receive **attachments**: images and PDFs (sent to the model as native multimodal content, only if the active model supports them - see the OpenRouter catalog) and text/Markdown/CSV/JSON files (`.txt`, `.md`, `.csv`, `.json`, `.log`, `.yaml`, `.yml` - their content is pasted directly into the message, readable by any model with no special modality needed).

## The 22 available tools

A tool not listed as read-only triggers a confirmation before its first execution in a conversation (unless the user clicked "always allow").

### Files (`tools/filesystem.py`)

| Tool | Read-only | Description |
|---|---|---|
| `read_file` | ✅ | Reads a text file's content |
| `list_files` | ✅ | Lists a directory's contents |
| `write_file` | ❌ | Writes (or overwrites) a file |
| `edit_file` | ❌ | Replaces an exact piece of text in a file with another, without rewriting the whole file |
| `delete_file` | ❌ | Deletes a file |
| `move_file` | ❌ | Moves or renames a file |

### Search (`tools/search.py`)

| Tool | Read-only | Description |
|---|---|---|
| `grep` | ✅ | Searches for a regular expression across files in a directory |
| `glob` | ✅ | Finds files matching a pattern (e.g. `**/*.py`) |

### Git (`tools/git.py`)

| Tool | Read-only | Description |
|---|---|---|
| `git_status` | ✅ | Short-format working tree status |
| `git_diff` | ✅ | Diff of unstaged changes |
| `git_commit` | ❌ | Stages changes and creates a commit |

### Execution (`tools/process.py`)

| Tool | Read-only | Description |
|---|---|---|
| `run_shell` | ❌ | Runs an arbitrary shell command and returns its output |
| `run_tests` | ❌ | Runs the project's test suite (pytest) |

`run_shell`/`run_tests` take a `directory` argument, forced to the active project's folder whenever the conversation has one (see [Projects and security](03-projects-and-security.md) - before this fix, the command ran in the harness's own folder, not the project's).

### Web (`tools/web.py`)

| Tool | Read-only | Description |
|---|---|---|
| `fetch_url` | ✅ | Fetches a URL's text content |
| `web_search` | ✅ | Searches the web, returns top result titles/URLs |

### Memory (`tools/memory.py`)

| Tool | Read-only | Description |
|---|---|---|
| `todo_write` | ✅ | Replaces the current task list (progress tracking on a multi-step task) |
| `remember` | ❌ | Saves a note to persistent memory - see [Memory](04-memory.md) for where it ends up |

`todo_write` lives purely in process memory (never persisted to disk, reset on restart) - a way for the model to keep track of a long task, not real storage.

### Sub-agents and background tasks (`tools/background.py`)

| Tool | Read-only | Description |
|---|---|---|
| `dispatch_subagent` | ❌ | Starts a background research sub-agent |
| `check_subagent` | ✅ | Checks a sub-agent's status/result |
| `start_background_task` | ❌ | Starts a long-running process (dev server, watcher...) |
| `stop_background_task` | ❌ | Stops a background task |
| `list_background_tasks` | ✅ | Lists this conversation's background tasks |

Details in [Multi-agent](05-multi-agent.md) and [Settings and integrations](07-settings-and-integrations.md).

## MCP tools

Beyond these 22 native tools, any connected MCP server (see [Settings and integrations](07-settings-and-integrations.md)) dynamically adds its own tools to the list - `mcp_client.py` merges them into the same registry (`TOOLS_REGISTRY`), so the model sees and calls them exactly like the native ones. They don't go through per-project sandboxing (their schemas aren't known ahead of time).

## The "brain": the system prompt

Every conversation starts with a system message (`build_system_message`, `chat_loop.py`) containing:
1. A base instruction ("concise and clear assistant").
2. If the conversation is linked to a project: the folder path, and a reminder that file operations are confined to it.
3. Global memory (if it has any content).
4. Project memory (if linked to one) or the conversation's own memory (otherwise).

That's it - no elaborate prompt engineering; most of the behavior comes from the tools themselves and their descriptions.
