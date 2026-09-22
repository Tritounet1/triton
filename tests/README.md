# Test coverage: desktop vs. web

Most tests exercise business logic that's identical regardless of
`TRITON_DEPLOYMENT_PROFILE` - the harness's own tool/session/model logic
doesn't know or care which profile it's running under, so it's tested
once and covers both. Only the files below are profile-aware; everything
else in this directory (and `app-desktop/src/*.test.tsx`) applies equally
to desktop and web.

## Backend (pytest)

| File | Covers |
|---|---|
| `test_deployment_profile.py` | The capability policy itself (`tool_is_allowed`/`path_is_allowed`/`project_is_allowed`) - what's allowed in each profile, with and without a remote workspace configured. |
| `test_web_deployment.py` | server.py's dual local/remote routing: chat tool dispatch, background tasks, snapshots, project create/delete, MCP/memory/subagent host-only bypasses, startup lifespan behavior (orchestrator resume, scheduled-task poll loop, workspace maintenance sweep). |
| `test_workspace_runner.py` | The isolated workspace runner's own HTTP surface: files/tools, background tasks, snapshots, per-workspace quotas, orphan/expired-snapshot cleanup. |
| `test_orchestrator_remote_workspace.py` | The multi-agent orchestrator's subtask tools routed through a remote workspace. |
| `test_subagents_sandbox.py` | Also covers `dispatch_subagent`'s own file tools routed through a remote workspace, alongside its desktop sandboxing tests. |
| `test_keychain_fallback.py` | The non-macOS secret storage path (Linux/Docker web deployments have no OS keychain). `test_keychain_integration.py` covers the real macOS Keychain and only runs there. |
| `test_web_runtime.py` | Web-only request-size/rate-limit config; no desktop equivalent. |
| `test_backup.py` | Includes the invariant that the export never contains `secrets.json`, relevant to both profiles now that `/backup` is reachable from web too. |

Run the whole suite with `uv run pytest -q` from `dev/harness/` - there's
no separate desktop/web pytest invocation; both profiles' code lives in
the same process and one run exercises both.

## Frontend (Vitest)

| File | Covers |
|---|---|
| `app-desktop/src/SettingsModal.test.tsx` | Which Settings categories show under `isWebDeployment`, with and without `remoteWorkspacesEnabled`. |

Everything else in `app-desktop/src/*.test.tsx` renders components that
don't branch on deployment profile at all. Run with `pnpm test` (alias
for `vitest run`) from `app-desktop/` - now wired into CI
(`.github/workflows/ci.yml`), which previously built the frontend
without ever running its test suite.
