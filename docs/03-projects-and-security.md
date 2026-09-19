# Projects and security

## What a "project" is here

A project (`storage/projects.py`) is just `{id, name, folder_path}` - a name and a local folder on the machine. Creating a project (`POST /projects`) only records this mapping; it doesn't copy or modify anything on disk.

A conversation can be linked to a project (`storage/sessions.py`'s `project_path`/`load_session_project`) - either from the moment it's created (starting a conversation "inside" a project), or never. That link has three direct consequences:

1. **Sandboxing**: every file operation is confined to the project's folder.
2. **System prompt**: the model is told the folder path and the constraint.
3. **Memory**: the conversation shares the project's memory instead of having its own (see [Memory](04-memory.md)).

## Per-folder sandboxing

`enforce_project_sandbox` (`tools/_shared.py`) runs before every tool call, for every conversation linked to a project. It:

- Checks that each "path" argument of a tool (`path`, `directory`, `source`/`destination` for `move_file`, `paths` for `git_commit`...) resolves inside the project's folder, including for a relative path or an attempt to escape via `../`.
- Auto-fills an omitted `directory` argument with the project's folder, for the tools it applies to (`list_files`, `grep`, `glob`, `git_status`, `git_diff`, `git_commit`, `run_shell`, `run_tests`, `start_background_task`) - without this, an omitted argument would default to the *harness's* own folder, not the project's.
- Returns an explicit error to the model if a path escapes the folder (`error: this conversation is scoped to the project folder...`), without ever running the operation.

This list is explicitly maintained in `SANDBOXED_PATH_ARGS` (`tools/_shared.py`) - a new tool with a path argument has to be added there by hand to be covered.

**Known limitation**: MCP tools (schemas unknown ahead of time) aren't covered. On macOS, `run_shell` and background tasks also run under a Seatbelt profile that confines filesystem writes to the project; Linux and Windows currently retain only the path/working-directory checks. Network access is not sandboxed.

## The write-tool safety net (snapshots)

A model can write, modify, or delete files with no human review step in between - especially the multi-agent `code` role, which has *no* confirmation at all. The safety net (`tools/snapshot.py`) addresses this: before a conversation's very first write into a project, the folder's state is captured automatically.

**Mechanism, depending on whether the folder is a git repo:**

- **Git folder**: a commit is built by hand (`git add -A` into a throwaway scratch index, `git write-tree`, `git commit-tree`), never touching the repo's real index or working tree. The resulting commit is "orphaned" (not attached to any branch), kept alive by a dedicated ref (`refs/triton/snapshots/<session_id>`) so git's garbage collector never sweeps it. It's invisible in a normal `git log` (needs `git log --all`, or targeting the ref directly).
- **Non-git folder**: Triton stores a manifest and the content needed to restore changed files in its internal snapshot storage; ignored build/dependency directories are excluded.

One restore point is created per write turn. Each point is finalized after the turn, so the history can restore either its state before or after that turn.

**Restore** (`POST /sessions/{id}/snapshot/restore`, the "Restore" button in the file panel, or the `/undo` command):
- Git: `git checkout <snapshot> -- .` (restores/overwrites files present in the snapshot) then `git clean -fd` (removes files created since, respecting `.gitignore`) then `git reset` (unstages, so the resulting state matches exactly what it was before).
- Non-git: only the files tracked by the selected internal snapshot are restored; the project is not blindly emptied.

Always behind an explicit UI confirmation - never triggered automatically.

## `run_shell`: what's isolated, what isn't

Before the fix, `run_shell`/`run_tests` received no `cwd` at all: the command ran in the *server's* own folder (the harness itself), not the project's - a real bug, not just a security concern (a command like `ls` listed the wrong folder). Fixed by adding a `directory` argument to both tools and routing it through the same `enforce_project_sandbox` as everything else.

On macOS, Seatbelt also blocks writes outside the project even when a command contains `cd ..`; the same protection is reused by background tasks. On Linux and Windows, do not treat the working-directory check as a complete shell sandbox.
