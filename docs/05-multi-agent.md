# Multi-agent

Two distinct mechanisms share the word "agent" in this project - worth not conflating:

- **The orchestrator** (`agents/orchestrator.py`): explicitly triggered by the user via `/multi-agents <task>`, splits a task across several specialized roles running in parallel.
- **Sub-agents** (`agents/subagents.py`): triggered by the *model itself* via the `dispatch_subagent` tool, to delegate a research task in the background without blocking the conversation.

## The orchestrator (`/multi-agents`)

Typed into the composer of a normal conversation (`/multi-agents fix the bugs and document module X`), it doesn't switch to a different page - the result folds into that same conversation, each subtask showing up as a fake tool call (same rendering as a real one).

**How it runs** (`POST /orchestrator`):

1. **Planning**: a "planner" model (role `orchestrator`) breaks the task into subtasks (6 max), each tagged with a role: `code`, `research`, `vision`, or `conversational`.
2. **Parallel dispatch**: each subtask runs in its own thread, with the model configured for its role (see [Settings and integrations](07-settings-and-integrations.md)) - up to 10 iterations each. No dependencies between them today, everything starts at once.
3. **Synthesis**: once every subtask finishes, the planner reviews their results and produces one final answer.

**What each role can do:**

| Role | Tools | Write access |
|---|---|---|
| `research`, `conversational`, `vision` | read-only (`read_file`, `list_files`, `grep`, `glob`, `fetch_url`, `web_search`, `git_status`, `git_diff`) | No |
| `code` (no project) | same tools, read-only | No |
| `code` (with a project) | + `write_file`, `edit_file`, `delete_file`, `move_file`, `run_tests` | **Yes** |

`run_shell` and `git_commit` are withheld from **every** role regardless of write access - running an arbitrary command or committing autonomously are a different order of risk than a plain file edit.

**Important**: a `code` role with write access gets **no human confirmation at all** - per-project sandboxing and the write-tool safety net (snapshots, see [Projects and security](03-projects-and-security.md)) are the only safety nets, not a substitute for real supervision.

**Known limitations**: an in-flight run doesn't survive a harness restart (everything lives in memory, `RUNS` in `orchestrator.py`); no dependencies between subtasks within a single run.

## Sub-agents (`dispatch_subagent`)

Unlike the orchestrator, it's the **model** that decides to delegate, mid-conversation - typically for a research task that would take a while and otherwise block the conversation. `dispatch_subagent(task)` starts an isolated agentic loop (up to 8 iterations) in a thread, strictly read-only (`read_file`, `list_files`, `grep`, `glob`, `fetch_url`, `web_search`, `git_status`, `git_diff`) - never writing, never running a command.

The main model keeps the conversation going in parallel and retrieves the result later via `check_subagent(task_id)` - with a guard against overly frequent polling (`MIN_CHECK_INTERVAL_SECONDS`, 10s) so an impatient model doesn't loop on it. The desktop app also shows sub-agent status live in a side panel (`SubagentsPanel.tsx`), so the user doesn't have to wait for the model's next call to see progress.
