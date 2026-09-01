# Desktop app

A Tauri app (a light native shell, system webview) with a React interface (Astryx design system). Talks exclusively to `server.py` over HTTP/SSE - no business logic is duplicated on the frontend beyond display.

## Project file panel (`ProjectFilePanel.tsx`)

Shown in the right-hand column whenever a conversation is linked to a project. Displays the folder's tree with, for recognized extensions (`.md`, `.html`, `.pdf` for now), a colored IDE-style icon instead of the generic file icon.

Also holds, whenever relevant to the current conversation:
- Active background tasks (`BackgroundTasksSection.tsx`).
- The write-tool safety net's banner (`SnapshotSection.tsx`) - only shown if a snapshot was taken for this conversation, with a "Restore" button (confirmation required before acting, see [Projects and security](03-projects-and-security.md)).

## Built-in file viewer (`FileViewerPanel.tsx`)

Clicking a `.md`/`.html`/`.pdf` file in the tree opens it in a dedicated panel (replaces the file panel in the same slot, Claude Desktop-style) instead of opening it in the system's default application:

- **PDF**: rendered natively via `<embed>`, relying on the webview's built-in PDF viewer (WKWebView on macOS) - no JS dependency added.
- **HTML**: rendered in a sandboxed `<iframe>` (`sandbox="allow-scripts"`, deliberately without `allow-same-origin` - the page's own JS can run but stays isolated from the rest of the app).
- **Markdown**: rendered through the same `Markdown` component used for chat messages.
- For HTML and Markdown, a **Preview / Code** toggle switches between the rendered view and the raw content.

Any other file type (anything not in this list) still opens with the system's default application, same as before this viewer existed.

## Attachments

Two distinct mechanisms depending on the file type:
- **Image / PDF**: sent as native multimodal content (8MB limit), only if the active model advertises support for it (OpenRouter catalog) - the "attach" button disables itself for these types otherwise.
- **Text** (`.txt`, `.md`, `.markdown`, `.csv`, `.json`, `.log`, `.yaml`, `.yml`, 200KB limit): the content is pasted directly into the message text, not sent as a binary attachment - any model understands it, no special modality required.

## Keyboard shortcuts

| Shortcut | Effect |
|---|---|
| `Cmd/Ctrl + K` | Opens search |
| `Cmd/Ctrl + N` | New conversation |
| `Escape` | Interrupts the reply in progress (only while one is streaming) |

## Sidebar: conversations and projects

Each row (conversation or project) has a single **⋯** button opening a menu with its actions (rename, export, pin, delete for a conversation; new conversation, rename, delete for a project), rather than several separate buttons permanently visible on the row.

Pinned conversations sort to the top of their list (global or a project's), sorted by recency below that.
