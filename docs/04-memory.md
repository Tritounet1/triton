# Memory

The `remember` tool saves a note that should stay available without the user having to repeat it. The question that raises: *available to whom, in which conversations?* Triton has three tiers, replacing an earlier single-flat-file system.

## The three tiers

| Tier | File | Scope |
|---|---|---|
| Conversation | `sessions/<id>.memory.md` | Private to one conversation that isn't linked to a project |
| Project | `project_memory/<project_id>.md` | Shared by every conversation in the same project, current ones and any created later |
| Global | `memory_global.md` | Shared by every conversation, period |

**How `remember` picks one** (`tools/memory.py`): does the calling conversation have a linked project?
- Yes → writes to the **project's** memory. In that case the conversation never gets its own memory file - the project's plays that role instead.
- No → writes to **that conversation's own** memory.

Global memory is never written by `remember` - it's scaffolding for later (see below), always loaded but currently empty.

## How it comes back into the prompt

`build_system_message` (`llm/chat_loop.py`), called once **when a conversation is created**:

1. Loads global memory (`storage/memory.py`) - always, regardless of the conversation.
2. Loads either the project's memory (if linked) or the conversation's own (otherwise) - never both, never another conversation's/project's.

**Important consequence**: memory is frozen at conversation creation time. A `remember` call made partway through doesn't retroactively appear in the system message already sent - it becomes visible in *future* conversations (or, for a project, in that same project's other conversations already open, once they're restarted).

## What doesn't exist yet

- **No search**: the whole of the relevant tier's memory is injected as one block, there's no relevance-based selection. A project with a lot of notes sees all of them, every new conversation.
- **Nothing writes to global memory** yet - the file exists (`memory_global.md`, at the repo root), always read, but no tool can add to it yet. Deliberately deferred.
- **No UI** to list/edit/delete a note by hand - `remember` is a one-way trip today.

A possible evolution (noted in `PLAN.md`) would be a lightweight RAG: turning each note into a vector (embedding) and injecting only the most relevant notes for the current message instead of the whole file - with, as a simpler intermediate step, a keyword search before jumping to embeddings.
