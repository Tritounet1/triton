import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import {
  ChatComposer,
  ChatComposerDrawer,
  ChatComposerInput,
  ChatLayout,
  ChatLayoutScrollButton,
  ChatMessage,
  ChatMessageBubble,
  ChatMessageList,
  ChatMessageMetadata,
  ChatSystemMessage,
  ChatToolCalls,
  type ChatComposerToken,
  type ChatComposerTrigger,
} from "@astryxdesign/core/Chat";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import { SideNav } from "@astryxdesign/core/SideNav";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { Theme } from "@astryxdesign/core/theme";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import {
  createStaticSource,
  type SearchableItem,
} from "@astryxdesign/core/Typeahead";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import "./App.css";
import { API_BASE, isWebDeployment } from "./api";
import { BackgroundTasksPanel } from "./BackgroundTasksPanel";
import { type BackgroundTask } from "./BackgroundTasksSection";
import {
  COMPACT_COMMAND,
  COST_COMMAND,
  createChatCommands,
  MODEL_COMMAND_PREFIX,
  MULTI_AGENT_PREFIX,
  REMEMBER_PREFIX,
  UNDO_COMMAND,
  YOLO_COMMAND,
} from "./chatCommands";
import { ConversationSidebarSection } from "./ConversationSidebarSection";
import {
  runChatConversationStream,
  type PendingConfirmation,
} from "./chatConversationStream";
import { DesktopTitlebar } from "./DesktopTitlebar";
import {
  assistantGroupModel,
  editFileTarget,
  formatSessionLabel,
  groupMessages,
  historyToMessages,
  isPdfDataUrl,
  parseEditFileEdits,
  parseToolDisplay,
  stripWebSearchSource,
  toBlocks,
  toolCallStatus,
  toolDiffStats,
  truncateBeforeTurn,
  userMessageAtTurn,
  webSearchSource,
  type ChatMsg,
  type EditFileEdit,
  type RawSessionMessage,
  type ToolCallLike,
  type ToolMsg,
} from "./chatMessages";
import { type OpenFile } from "./fileViewer";
import { FileViewerPanel } from "./FileViewerPanel";
import { formatArgs } from "./format";
import { ImagePreviewDialog } from "./ImagePreviewDialog";
import {
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  FileIcon,
  GearIcon,
  ImageIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  RefreshIcon,
  SunIcon,
  XIcon,
} from "./icons";
import { modelAvatar } from "./modelFamilies";
import { NewProjectModal } from "./NewProjectModal";
import { notifyIfBackground } from "./notifications";
import { ProjectFilePanel } from "./ProjectFilePanel";
import { ProjectSidebarSection } from "./ProjectSidebarSection";
import { RichCard } from "./RichCard";
import { richCardFromToolCall } from "./richCardData";
import { SearchPage } from "./SearchPage";
import { SettingsModal } from "./SettingsModal";
import { SidebarHeader } from "./SidebarHeader";
import {
  describeSnapshotDiff,
  type SnapshotDiff,
  type SnapshotPoint,
} from "./snapshotDiff";
import { SnapshotHistoryView } from "./SnapshotHistoryView";
import { SubagentsPanel } from "./SubagentsPanel";
import { TaskView } from "./TaskView";
import { useDeploymentCapabilities } from "./useDeploymentCapabilities";

// past this idle gap with no SSE event, treat it as a server-side lull
// rather than active token streaming - see awaitingSseEvent.
const SSE_IDLE_MS = 500;
// distance (px) from the bottom past which the scroll-to-bottom button
// shows - see showScrollButton.
const SCROLL_BUTTON_THRESHOLD_PX = 100;
// must match MAX_ATTACHMENT_BYTES on the server (server.py).
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
// text files are inlined into the message text (not sent as a binary
// attachment, see PendingTextAttachment below), so a much lower limit
// than images/PDFs applies.
const MAX_TEXT_ATTACHMENT_BYTES = 200 * 1024;
const TEXT_ATTACHMENT_EXTENSIONS = [
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".log",
  ".yaml",
  ".yml",
];
// slash-triggered menu (Notion/Discord style), via ChatComposerInput's
// own trigger mechanism.
const SLASH_COMMANDS: SearchableItem<{ description: string }>[] = [
  {
    id: "multi-agents",
    label: "multi-agents",
    auxiliaryData: {
      description:
        "Répartit la tâche entre plusieurs agents spécialisés (recherche, code, rédaction...)",
    },
  },
  {
    id: "model",
    label: "model",
    auxiliaryData: {
      description: "Change le modèle de cette conversation (ex. /model gpt-5)",
    },
  },
  {
    id: "cost",
    label: "cost",
    auxiliaryData: {
      description:
        "Affiche le coût et les tokens utilisés dans cette conversation",
    },
  },
  {
    id: "undo",
    label: "undo",
    auxiliaryData: {
      description:
        "Restaure le dossier du projet à l'état d'avant cette session (filet de sécurité)",
    },
  },
  {
    id: "remember-session",
    label: "remember session",
    auxiliaryData: {
      description:
        "Note quelque chose pour cette conversation (ou son projet, si elle en a un)",
    },
  },
  {
    id: "remember-global",
    label: "remember global",
    auxiliaryData: {
      description:
        "Note quelque chose dans la mémoire globale, partagée par toutes les conversations",
    },
  },
  {
    id: "compact",
    label: "compact",
    auxiliaryData: {
      description:
        "Résume les échanges les plus anciens dès maintenant, sans attendre que le contexte soit plein",
    },
  },
  {
    id: "yolo",
    label: "yolo",
    auxiliaryData: {
      description:
        "Active/désactive le mode YOLO pour cette conversation : plus de demande d'autorisation avant une action (écriture, commande...)",
    },
  },
];

const slashCommandSource = createStaticSource(SLASH_COMMANDS);

const composerTriggers: ChatComposerTrigger[] = [
  {
    character: "/",
    searchSource: slashCommandSource,
    menuLabel: "Commandes",
    emptySearchResultsText: "Aucune commande",
    // a token (pill), not plain text, so the command reads visually
    // distinct - `value` is what ends up in the sent message, same as the
    // old plain-text insert, so sendMessage's own prefix parsing is
    // unaffected.
    onSelect: (item): ChatComposerToken => ({
      value: `/${item.label} `,
      label: `/${item.label}`,
      variant: "neutral",
    }),
    renderItem: (item) => {
      const description = (item as SearchableItem<{ description: string }>)
        .auxiliaryData?.description;
      return (
        <div className="flex flex-col gap-0.5 px-2 py-1.5">
          <Text size="sm" weight="medium">
            /{item.label}
          </Text>
          {description && (
            <Text size="2xs" color="secondary">
              {description}
            </Text>
          )}
        </div>
      );
    },
  },
];

interface PendingAttachment {
  name: string;
  dataUrl: string;
}

/** Text file pending send - unlike PendingAttachment (image/PDF), never
 * sent as a binary attachment: its content is inlined into the message
 * text at send time (see sendMessage), so any model can read it without
 * needing vision/file support. */
interface PendingTextAttachment {
  name: string;
  content: string;
}

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
  pinned: boolean;
}

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

/** Before/after for an edit_file call, built from its own
 * old_string/new_string arguments (not the result) - one solid red block
 * then one solid green block, no line-level diff, enough to see what
 * changed at a glance. */
function EditFileDiff({
  oldString,
  newString,
}: {
  oldString: string;
  newString: string;
}) {
  return (
    <div className="max-h-64 overflow-y-auto rounded-lg font-mono text-xs">
      {oldString !== "" &&
        oldString.split("\n").map((line, i) => (
          <div
            key={`old-${i}`}
            className="whitespace-pre bg-error-muted px-2 py-0.5 text-error"
          >
            <span className="select-none opacity-60">- </span>
            {line}
          </div>
        ))}
      {newString !== "" &&
        newString.split("\n").map((line, i) => (
          <div
            key={`new-${i}`}
            className="whitespace-pre bg-success-muted px-2 py-0.5 text-success"
          >
            <span className="select-none opacity-60">+ </span>
            {line}
          </div>
        ))}
    </div>
  );
}

/** Same rendering as EditFileDiff, but for a write_file call: there's no
 * "before" in its arguments (just the new `content`), so this fetches
 * the file's current state via the same endpoint FileViewerPanel.tsx
 * uses - a 404 (new file) just shows the green block alone. */
function WriteFileDiff({
  projectId,
  path,
  newContent,
}: {
  projectId: string;
  path: string;
  newContent: string;
}) {
  const [oldContent, setOldContent] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  // no synchronous `loaded` reset here (forbidden in an effect, see
  // McpSettings.tsx) - each write_file confirmation is sequential, so
  // this component remounts each time rather than reusing state.
  useEffect(() => {
    fetch(
      `${API_BASE}/projects/${projectId}/file?path=${encodeURIComponent(path)}`,
    )
      .then((r) => (r.ok ? r.text() : null))
      .then((text) => {
        setOldContent(text);
      })
      .catch(() => {
        setOldContent(null);
      })
      .finally(() => {
        setLoaded(true);
      });
  }, [projectId, path]);

  if (!loaded) {
    return (
      <Spinner
        size="sm"
        shade="subtle"
        aria-label="Chargement du contenu actuel"
      />
    );
  }

  return <EditFileDiff oldString={oldContent ?? ""} newString={newContent} />;
}

/** One EditFileDiff per hunk, grouped by file (path header once there's
 * more than one) - the full detail view for an edit_file call, both for
 * the confirmation preview and for history. */
function EditFileEdits({ edits }: { edits: EditFileEdit[] }) {
  const byPath = new Map<string, EditFileEdit[]>();
  for (const e of edits) {
    const list = byPath.get(e.path) ?? [];
    list.push(e);
    byPath.set(e.path, list);
  }
  return (
    <div className="flex flex-col gap-3">
      {[...byPath.entries()].map(([path, hunks]) => (
        <div key={path} className="flex flex-col gap-1">
          {byPath.size > 1 && (
            <Text size="2xs" color="secondary" className="font-mono">
              {path}
            </Text>
          )}
          {hunks.map((h, i) => (
            <EditFileDiff
              key={i}
              oldString={h.old_string}
              newString={h.new_string}
            />
          ))}
        </div>
      ))}
    </div>
  );
}

function toolResultDetail(t: ToolCallLike): ReactNode {
  if (t.tool === "edit_file") {
    const edits = parseEditFileEdits(t.args);
    if (edits.length > 0) return <EditFileEdits edits={edits} />;
  }
  const { content } = t.args;
  if (t.tool === "write_file" && typeof content === "string") {
    // no reliable "before" to show here (unlike the confirmation preview
    // above, which fetches the file's *current* state) - this is history,
    // and fetching "now" would only match the pre-call state if nothing
    // changed since, not guaranteed. The written content is a known fact.
    return <EditFileDiff oldString="" newString={content} />;
  }
  const result =
    t.tool === "web_search" ? stripWebSearchSource(t.result) : t.result;
  return (
    <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
      {result}
    </pre>
  );
}

/** A multi-agent subtask's detail: its description, then its own tool
 * calls (same ChatToolCalls component, nested) live-updated while it
 * runs, then its result once done. */
function multiAgentSubtaskDetail(t: ToolMsg): ReactNode {
  const calls = t.subtaskToolCalls ?? [];
  return (
    <div className="flex flex-col gap-2">
      {t.subtaskDescription && (
        <p className="text-xs text-secondary">{t.subtaskDescription}</p>
      )}
      {calls.length > 0 && (
        <ChatToolCalls
          defaultIsExpanded
          calls={calls.map((c) => ({
            name: c.tool,
            status: toolCallStatus(c.result),
            node:
              c.tool === "web_search" ? webSearchSource(c.result) : undefined,
            target:
              c.tool === "edit_file"
                ? editFileTarget(c.args)
                : formatArgs(c.args),
            ...toolDiffStats(c),
            resultDetail: toolResultDetail(c),
          }))}
        />
      )}
      {t.result && (
        <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
          {t.result}
        </pre>
      )}
    </div>
  );
}

function App() {
  const capabilities = useDeploymentCapabilities();
  // on macOS/Tauri the window uses an overlay titlebar. Keeps the native
  // bar in the dev browser and other platforms, while leaving room for
  // the traffic-light buttons on desktop.
  const usesMacTitlebarOverlay =
    typeof window !== "undefined" &&
    "__TAURI_INTERNALS__" in window &&
    navigator.userAgent.includes("Mac");
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  // IDs of conversations with a send in flight ("" for a brand-new one
  // the server hasn't named yet, see sendMessage) - lets switching
  // conversations mid-stream (like ChatGPT/Claude) not block it: each
  // sendMessage tracks its own send independently of what's on screen.
  // `sending` (defined below, used everywhere else in the UI) only
  // reflects the currently displayed conversation.
  const [sendingSessionIds, setSendingSessionIds] = useState<Set<string>>(
    () => new Set(),
  );
  // model tied to a request still in flight - can differ from the
  // default chat model, e.g. a one-off Gemini image.
  const [inFlightModels, setInFlightModels] = useState<Record<string, string>>(
    {},
  );
  // true once no SSE event has arrived for SSE_IDLE_MS on the displayed
  // conversation - covers the lull while a server-side tool runs right
  // after some assistant text (e.g. "Writing file X." followed by a slow
  // write_file): showTypingPlaceholder used to hide the loader as soon as
  // assistant text showed, even with nothing following - see sendMessage's
  // noteSseEvent, called on every event.
  const [awaitingSseEvent, setAwaitingSseEvent] = useState(false);
  const [apiModel, setApiModel] = useState<string | null>(null);
  // same idea as the default chat model, but for the Images endpoint -
  // the two settings stay fully independent.
  const [imageModel, setImageModel] = useState<string | null>(null);
  const [oneShotChatModel, setOneShotChatModel] = useState<string | null>(null);
  const [oneShotImageModel, setOneShotImageModel] = useState<string | null>(null);
  const [imageMode, setImageMode] = useState(false);
  const [previewImage, setPreviewImage] = useState<string | null>(null);
  // model specific to the current conversation, set via /model (PUT
  // /sessions/{id}/model) - overrides apiModel (the global default) while
  // set. null = no override, follows the global model.
  const [sessionModelOverride, setSessionModelOverride] = useState<
    string | null
  >(null);
  // /yolo for THIS conversation (see GET/POST /sessions/{id}/yolo) - shows
  // a persistent banner while active, not just a toggle toast, since it
  // silently changes what every following message does.
  const [yoloEnabled, setYoloEnabled] = useState(false);
  // OpenRouter catalog (id + capabilities), fetched once at startup, to
  // know if the current model supports images/PDFs (enables/filters the
  // composer's attach button) without duplicating that logic server-side.
  const [modelsCatalog, setModelsCatalog] = useState<
    {
      id: string;
      name: string;
      supports_images: boolean;
      supports_files: boolean;
    }[]
  >([]);
  const [imageModelsCatalog, setImageModelsCatalog] = useState<
    { id: string; name: string; description: string }[]
  >([]);
  const [pendingAttachments, setPendingAttachments] = useState<
    PendingAttachment[]
  >([]);
  const [pendingTextAttachments, setPendingTextAttachments] = useState<
    PendingTextAttachment[]
  >([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // counter rather than a plain boolean: dragenter/dragleave also fire when
  // hovering children (the message list, the composer...), so a plain
  // "enter = true / leave = false" flickers every time a child boundary is
  // crossed within the drop zone itself. The counter only drops back to 0
  // (hides the overlay) once truly out of all nested children.
  const [dragDepth, setDragDepth] = useState(0);
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
  const sending = sendingSessionIds.has(sessionId ?? "");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [editingProjectValue, setEditingProjectValue] = useState("");
  const [deletingSession, setDeletingSession] = useState<Session | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [showProjectForm, setShowProjectForm] = useState(false);
  const [deletingProject, setDeletingProject] = useState<Project | null>(null);
  // confirmation for /undo (see handleUndoCommand) - same AlertDialog as
  // the deletions above, a destructive action so no shortcut without
  // confirmation even from the composer. /undo always targets the most
  // recent restore point (undo the last message) - "undo the whole
  // session" is a file panel action (SnapshotSection.tsx), not this
  // text command.
  const [undoTarget, setUndoTarget] = useState<SnapshotPoint | null>(null);
  const [undoing, setUndoing] = useState(false);
  // same diff as SnapshotSection.tsx for the same confirmation - loaded
  // on open, not on mount (see snapshotDiff.ts).
  const [undoDiff, setUndoDiff] = useState<SnapshotDiff | null>(null);
  const [collapsedProjectIds, setCollapsedProjectIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [fileRefreshTick, setFileRefreshTick] = useState(0);
  // file open in the viewer (PDF/HTML/Markdown) - replaces
  // ProjectFilePanel in the same slot while open (see FileViewerPanel.tsx).
  const [openFile, setOpenFile] = useState<OpenFile | null>(null);
  // Claude-desktop-style collapsible sidebar: collapsed, it disappears
  // entirely (not just an icon rail) - hovering the left edge shows it
  // temporarily (sidebarPeeking), the button pins it open for good.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("triton_sidebar_collapsed") === "1",
  );
  const [sidebarPeeking, setSidebarPeeking] = useState(false);
  const toggleSidebar = () => {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    setSidebarPeeking(false);
    localStorage.setItem("triton_sidebar_collapsed", next ? "1" : "0");
  };
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  // turnIndex (1-based, see groupMessages) of the user message being
  // edited, null if none - only one at a time, edited in place in its
  // own bubble (see the "user" group render below).
  const [editingTurnIndex, setEditingTurnIndex] = useState<number | null>(null);
  const [editingText, setEditingText] = useState("");
  const [pendingConfirmation, setPendingConfirmation] =
    useState<PendingConfirmation | null>(null);
  // collapsed by default (Claude Desktop style) - args/diff hidden until
  // clicked.
  const [confirmationDetailsExpanded, setConfirmationDetailsExpanded] =
    useState(false);
  // reset to false on each new confirmation (different id, including
  // returning to a conversation with one pending, see switchSession): a
  // synchronous adjustment during render (the official React "adjust
  // state when a prop changes" pattern), not in an effect -
  // react-hooks/set-state-in-effect forbids that.
  const [lastConfirmationId, setLastConfirmationId] = useState<string | null>(
    null,
  );
  if ((pendingConfirmation?.id ?? null) !== lastConfirmationId) {
    setLastConfirmationId(pendingConfirmation?.id ?? null);
    setConfirmationDetailsExpanded(false);
  }
  // one AbortController/pending confirmation per conversation (key:
  // sessionId, or "" for a brand-new one, same convention as
  // sendingSessionIds) rather than a single global value: sendMessage()
  // for a conversation no longer displayed must stay cancelable/answerable
  // once we return to it, without being overwritten by another
  // conversation's send meanwhile. Refs, not state: nothing here needs a
  // re-render while its conversation isn't the displayed one - see
  // sendMessage/cancelMessage/respondToConfirmation.
  const abortControllersRef = useRef<Map<string, AbortController>>(new Map());
  const pendingConfirmationsRef = useRef<Map<string, PendingConfirmation>>(
    new Map(),
  );
  // SSE-idle timer (see awaitingSseEvent) - only one conversation is
  // displayed at a time, so no per-session Map needed unlike the refs
  // just above.
  const sseIdleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // scroll-to-bottom button, replacing ChatLayout's own default
  // (scrollButton), whose "new messages" state stays shown until clicked
  // even after scrolling back down (its own logic only resets via an
  // explicit dismiss()). Here, visible/label depend only on the current
  // scroll position - no "stuck" state.
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);
  const [hasNewMessage, setHasNewMessage] = useState(false);

  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom =
        el.scrollHeight - el.scrollTop - el.clientHeight;
      const scrolledUp = distanceFromBottom > SCROLL_BUTTON_THRESHOLD_PX;
      setShowScrollButton(scrolledUp);
      if (!scrolledUp) setHasNewMessage(false);
    }
    el.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      el.removeEventListener("scroll", onScroll);
    };
  }, [sessionId]);

  // only flags "new messages" when a message was actually added (not
  // just text accumulating into the last one, see scheduleFlush in
  // sendMessage) while already scrolled up - no point flagging it at the
  // bottom, ChatLayout's follow-scroll keeps us there anyway. Adjusted
  // during render (not in an effect, see McpSettings.tsx), same mechanism
  // as lastConfirmationId above.
  const [lastMessagesLength, setLastMessagesLength] = useState(messages.length);
  if (messages.length !== lastMessagesLength) {
    setLastMessagesLength(messages.length);
    if (showScrollButton) setHasNewMessage(true);
  }
  // IDs of subagents dispatched in the ACTIVE conversation (reset on
  // conversation change) - lets the model auto-resume once one finishes,
  // instead of waiting indefinitely for a new user message.
  const pendingSubagentIdsRef = useRef<Set<string>>(new Set());
  // kept up to date after each render (effect with no dependency array),
  // read from a standalone timer (setInterval) rather than a closure
  // frozen at render/effect start - avoids restarting that timer on every
  // keystroke/state change (see cancelMessage/useCallback above for the
  // same issue). Direct mutation during render is forbidden by
  // react-hooks/refs, hence the effect.
  const sendingRef = useRef(sending);
  const inputRef = useRef(input);
  // currently displayed conversation, read by an in-flight sendMessage()
  // (possibly for ANOTHER conversation, started before navigating away)
  // to check on each SSE event whether its own session_id still matches
  // what's displayed - otherwise it keeps running in the background
  // without touching `messages` (see sendMessage). A ref rather than
  // reading `sessionId` directly: an already-running sendMessage's
  // closure captured its own frozen sessionId, this stays current even
  // after navigating away.
  const displayedSessionIdRef = useRef(sessionId);
  const sendMessageRef = useRef((_text: string): void => undefined);
  useEffect(() => {
    sendingRef.current = sending;
    inputRef.current = input;
    displayedSessionIdRef.current = sessionId;
  });
  const [themeMode, setThemeMode] = useState<"light" | "dark">(() =>
    localStorage.getItem("triton_theme") === "light" ? "light" : "dark",
  );
  const [view, setView] = useState<
    "chat" | "task" | "search" | "snapshot_history"
  >("chat");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [backgroundTasks, setBackgroundTasks] = useState<BackgroundTask[]>([]);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  function toggleTheme() {
    setThemeMode((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("triton_theme", next);
      return next;
    });
  }

  function refreshApiModel() {
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { ok: boolean; model: string } | null) => {
        setApiModel(data?.model ?? null);
      })
      .catch(() => {
        setApiModel(null);
      });
  }

  function refreshImageModel() {
    fetch(`${API_BASE}/settings/image_model`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { model: string } | null) => {
        setImageModel(data?.model ?? null);
      })
      .catch(() => {
        setImageModel(null);
      });
  }

  // returns the loaded list (in addition to updating state) so the initial
  // mount can read the restored session's project_id off it - `setSessions`
  // alone wouldn't be visible yet within the same effect pass.
  function loadSessions(): Promise<Session[]> {
    return fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Session[]) => {
        const reversed = [...list].reverse();
        setSessions(reversed);
        return reversed;
      })
      .catch(() => {
        // API unreachable: sidebar stays empty, app doesn't crash
        return [];
      });
  }

  function loadProjects() {
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Project[]) => {
        setProjects(list);
      })
      .catch(() => {
        // API unreachable: project list stays empty
      });
  }

  async function confirmDeleteProject() {
    if (!deletingProject) return;
    const id = deletingProject.id;
    setDeletingProject(null);

    const res = await fetch(`${API_BASE}/projects/${id}`, { method: "DELETE" });
    if (res.ok) {
      setProjects((await res.json()) as Project[]);
      if (activeProjectId === id) setActiveProjectId(null);
      void loadSessions();
    }
  }

  function startRename(session: Session) {
    setEditingSessionId(session.id);
    setEditingValue(session.title ?? formatSessionLabel(session.id));
  }

  async function commitRename(id: string) {
    const title = editingValue.trim();
    setEditingSessionId(null);
    if (!title) return;

    await fetch(`${API_BASE}/sessions/${id}/title`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    setSessions((prev) => prev.map((s) => (s.id === id ? { ...s, title } : s)));
  }

  async function togglePin(session: Session) {
    const pinned = !session.pinned;
    // optimistic: sidebar re-sorts immediately, no waiting on the
    // round-trip for a low-risk boolean toggle
    setSessions((prev) =>
      prev.map((s) => (s.id === session.id ? { ...s, pinned } : s)),
    );
    await fetch(`${API_BASE}/sessions/${session.id}/pin`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pinned }),
    });
  }

  function startRenameProject(project: Project) {
    setEditingProjectId(project.id);
    setEditingProjectValue(project.name);
  }

  async function commitRenameProject(id: string) {
    const name = editingProjectValue.trim();
    setEditingProjectId(null);
    if (!name) return;

    const res = await fetch(`${API_BASE}/projects/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    if (res.ok) setProjects((await res.json()) as Project[]);
  }

  async function confirmDeleteSession() {
    if (!deletingSession) return;
    setIsDeleting(true);

    try {
      await fetch(`${API_BASE}/sessions/${deletingSession.id}`, {
        method: "DELETE",
      });
      setSessions((prev) => prev.filter((s) => s.id !== deletingSession.id));
      if (deletingSession.id === sessionId) {
        startNewSession();
      }
    } finally {
      setIsDeleting(false);
      setDeletingSession(null);
    }
  }

  function loadHistory(id: string) {
    fetch(`${API_BASE}/sessions/${id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((raw: RawSessionMessage[] | null) => {
        if (raw) setMessages(historyToMessages(raw));
      })
      .catch(() => {
        // session not found server-side: keep local history as-is
      });
  }

  useEffect(() => {
    refreshApiModel();
    refreshImageModel();

    fetch(`${API_BASE}/openrouter/models`)
      .then((r) => (r.ok ? r.json() : []))
      .then(
        (
          data: {
            id: string;
            name: string;
            supports_images: boolean;
            supports_files: boolean;
          }[],
        ) => {
          setModelsCatalog(data);
        },
      )
      .catch(() => {
        // OpenRouter API unreachable: the "attach" button stays disabled
      });

    fetch(`${API_BASE}/openrouter/image-models`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: { id: string; name: string; description: string }[]) => {
        setImageModelsCatalog(data);
      })
      .catch(() => {
        // image mode stays available, selector just keeps the configured
        // default model instead of a fresh list
      });

    // only on startup, for an already-known session (localStorage) - must
    // not re-trigger when sendMessage() sets sessionId itself, or it races
    // the ongoing stream.
    const stored = localStorage.getItem("triton_session_id");
    if (stored) loadHistory(stored);

    // switchSession() normally derives activeProjectId from the in-memory
    // session list, but the restored session at startup doesn't go through
    // switchSession - without this the project folder panel stays hidden
    // until the user switches conversations and back (user-reported bug).
    void loadSessions().then((list) => {
      if (stored)
        setActiveProjectId(
          list.find((s) => s.id === stored)?.project_id ?? null,
        );
    });
    if (!isWebDeployment || capabilities.projects) {
      loadProjects();
    }
  }, [capabilities.projects]);

  // auto-nudges the model once a subagent dispatched from the active
  // conversation finishes: otherwise the turn ends as soon as the model
  // replies in text (no tool call) and nothing brings it back to check the
  // result until the user sends a new message. Reads sending/input via refs
  // (kept current on each render above) rather than restarting this timer
  // on every keystroke/state change.
  useEffect(() => {
    const interval = setInterval(() => {
      if (pendingSubagentIdsRef.current.size === 0) return;
      if (sendingRef.current || inputRef.current.trim()) return;

      fetch(`${API_BASE}/subagents`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data: { id: string; task: string; status: string }[]) => {
          const finished = data.find(
            (t) =>
              pendingSubagentIdsRef.current.has(t.id) && t.status !== "running",
          );
          if (!finished) return;
          pendingSubagentIdsRef.current.delete(finished.id);
          notifyIfBackground("Sous-agent terminé", finished.task);
          sendMessageRef.current(
            `(vérification automatique) Le sous-agent ${finished.id} a terminé, ` +
              "regarde son résultat avec check_subagent et continue la tâche.",
          );
        })
        .catch(() => {
          // offline: retried on the next interval
        });
    }, 4000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  // background tasks (start_background_task) for the active conversation:
  // shown in the right-side panel (BackgroundTasksPanel / ProjectFilePanel)
  // regardless of the current view, to stay reachable while the model works.
  useEffect(() => {
    if (!capabilities.background_tasks || !sessionId) return;
    let cancelled = false;
    function load() {
      fetch(`${API_BASE}/background_tasks?session_id=${sessionId}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data: BackgroundTask[]) => {
          if (!cancelled) setBackgroundTasks(data);
        })
        .catch(() => {
          // offline: retried on the next interval
        });
    }
    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [capabilities.background_tasks, sessionId]);

  // model override for the current conversation (see /model): no synchronous
  // reset to null here (not allowed in an effect - same guard as
  // McpSettings.tsx), so on sessionId change a stale override can briefly
  // stay shown until the request answers - same tradeoff already accepted in
  // SnapshotSection.tsx. Explicit reset happens in switchSession/
  // startNewSession/startProjectSession (event handlers, not an effect, so a
  // synchronous setState there is fine).
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}/model`)
      .then((r) => (r.ok ? r.json() : { model: null }))
      .then((data: { model: string | null }) => {
        setSessionModelOverride(data.model);
      })
      .catch(() => {
        setSessionModelOverride(null);
      });
  }, [sessionId]);

  // same principle as the sessionModelOverride effect above (no synchronous
  // reset here, done in switchSession/startNewSession/startProjectSession
  // instead).
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}/yolo`)
      .then((r) => (r.ok ? r.json() : { enabled: false }))
      .then((data: { enabled: boolean }) => {
        setYoloEnabled(data.enabled);
      })
      .catch(() => {
        setYoloEnabled(false);
      });
  }, [sessionId]);

  function openTask(id: string) {
    setActiveTaskId(id);
    setView("task");
  }

  function stopTask(id: string) {
    fetch(`${API_BASE}/background_tasks/${id}/stop`, { method: "POST" }).catch(
      () => {
        // offline: the next poll reflects real state anyway
      },
    );
  }

  function deleteTask(id: string) {
    setBackgroundTasks((prev) => prev.filter((t) => t.id !== id));
    fetch(`${API_BASE}/background_tasks/${id}`, { method: "DELETE" }).catch(
      () => {
        // offline: the next poll brings it back if the delete didn't
        // actually happen server-side
      },
    );
  }

  // `sending` is no longer a reason to block switching conversations (see
  // sendMessage): an in-flight response for the conversation being left
  // keeps running in the background, filtered by its own session_id rather
  // than writing into the `messages` of whichever one is now displayed.
  function switchSession(id: string) {
    setView("chat");
    if (id === sessionId) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    setActiveProjectId(sessions.find((s) => s.id === id)?.project_id ?? null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    // restores a pending tool confirmation if this conversation has one
    // (see pendingConfirmationsRef in sendMessage) - null otherwise, so the
    // conversation being left doesn't keep its confirmation shown.
    setPendingConfirmation(pendingConfirmationsRef.current.get(id) ?? null);
    loadHistory(id);
  }

  const startNewSession = useCallback(() => {
    setView("chat");
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    setPendingConfirmation(null);
  }, [setView, setOpenFile]);

  function startProjectSession(projectId: string) {
    setView("chat");
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(projectId);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    setOpenFile(null);
    setSessionModelOverride(null);
    setYoloEnabled(false);
    setAwaitingSseEvent(false);
    setPendingConfirmation(null);
  }

  function toggleProjectCollapsed(projectId: string) {
    setCollapsedProjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(projectId)) {
        next.delete(projectId);
      } else {
        next.add(projectId);
      }
      return next;
    });
  }

  function isTextAttachmentFile(file: File): boolean {
    if (file.type.startsWith("text/")) return true;
    const lower = file.name.toLowerCase();
    return TEXT_ATTACHMENT_EXTENSIONS.some((ext) => lower.endsWith(ext));
  }

  function handleFilesSelected(fileList: FileList | null) {
    if (!fileList) return;
    for (const file of Array.from(fileList)) {
      if (isTextAttachmentFile(file)) {
        if (imageMode) {
          setMessages((prev) => [
            ...prev,
            {
              kind: "error",
              text: "La génération d’images accepte uniquement des images de référence.",
              time: Date.now(),
            },
          ]);
          continue;
        }
        if (file.size > MAX_TEXT_ATTACHMENT_BYTES) {
          setMessages((prev) => [
            ...prev,
            {
              kind: "error",
              text: `« ${file.name} » dépasse la limite de ${MAX_TEXT_ATTACHMENT_BYTES / 1024} Ko pour un fichier texte, ignorée.`,
              time: Date.now(),
            },
          ]);
          continue;
        }
        void file.text().then((content) => {
          setPendingTextAttachments((prev) => [
            ...prev,
            { name: file.name, content },
          ]);
        });
        continue;
      }

      const isImage = file.type.startsWith("image/");
      const isPdf = file.type === "application/pdf";
      if (
        (isImage && !imageMode && !supportsImages) ||
        (isPdf && (imageMode || !supportsFiles)) ||
        (!isImage && !isPdf)
      ) {
        continue;
      }
      if (file.size > MAX_ATTACHMENT_BYTES) {
        setMessages((prev) => [
          ...prev,
          {
            kind: "error",
            text: `« ${file.name} » dépasse la limite de 8 Mo, ignorée.`,
            time: Date.now(),
          },
        ]);
        continue;
      }
      const reader = new FileReader();
      reader.onload = () => {
        const dataUrl = reader.result;
        if (typeof dataUrl !== "string") return;
        setPendingAttachments((prev) => [
          ...prev,
          { name: file.name, dataUrl },
        ]);
      };
      reader.readAsDataURL(file);
    }
  }

  /** Paste an image (e.g. a screenshot) from the clipboard: e.clipboardData.files
   * is already a native FileList, exactly what handleFilesSelected expects
   * (same path as the file picker and drag-and-drop) - just pass it through.
   * Leaves default behavior alone when nothing pasted is a file (pasting
   * plain text into the composer must stay intact). */
  function handlePaste(e: React.ClipboardEvent) {
    if (e.clipboardData.files.length === 0) return;
    e.preventDefault();
    handleFilesSelected(e.clipboardData.files);
  }

  function removeAttachment(index: number) {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  function removeTextAttachment(index: number) {
    setPendingTextAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  async function copyToClipboard(text: string, index: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => {
      setCopiedIndex((current) => (current === index ? null : current));
    }, 1500);
  }

  function startEditingMessage(turnIndex: number, text: string) {
    setEditingTurnIndex(turnIndex);
    setEditingText(text);
  }

  function cancelEditingMessage() {
    setEditingTurnIndex(null);
    setEditingText("");
  }

  async function submitEditedMessage() {
    if (editingTurnIndex === null) return;
    const turnIndex = editingTurnIndex;
    const text = editingText;
    setEditingTurnIndex(null);
    setEditingText("");
    await sendMessage(text, turnIndex);
  }

  /** Resends the exact same turn (same text, same attachments) - turnIndex/msg
   * come from the "user" group preceding the response being regenerated
   * (see precedingTurnIndex in groupMessages). */
  async function regenerateResponse(
    turnIndex: number,
    msg: Extract<ChatMsg, { kind: "user" }>,
  ) {
    const attachments: PendingAttachment[] = [
      ...(msg.images ?? []).map((dataUrl) => ({ name: "", dataUrl })),
      ...(msg.files ?? []).map((f) => ({ name: f.name, dataUrl: f.dataUrl })),
    ];
    await sendMessage(msg.text, turnIndex, attachments);
  }

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;
  // eslint-disable-next-line react-hooks/refs
  const commands = createChatCommands({
    sessionId,
    activeProjectId,
    activeProject,
    modelsCatalog,
    undoTarget,
    sending,
    pendingAttachments,
    pendingTextAttachments,
    oneShotImageModel,
    imageModel,
    getDisplayedSessionId: () => displayedSessionIdRef.current,
    setDisplayedSessionId: (id: string) => {
      displayedSessionIdRef.current = id;
    },
    getAbortControllers: () => abortControllersRef.current,
    setInput,
    setMessages,
    setSessions,
    setSessionId,
    setSessionModelOverride,
    setUndoDiff,
    setUndoTarget,
    setUndoing,
    setFileRefreshTick,
    setYoloEnabled,
    setSendingSessionIds,
    setInFlightModels,
    setOneShotImageModel,
    setPendingAttachments,
    setImageMode,
    setPreviewImage,
    loadSessions,
  });
  const {
    markSending,
    markInFlightModel,
    moveSendingKey,
    dispatchMultiAgent,
    handleCostCommand,
    handleModelCommand,
    handleUndoCommand,
    confirmUndo,
    handleRememberCommand,
    handleCompactCommand,
    handleYoloCommand,
    requestImageChange,
    generateImage,
  } = commands;

  async function sendMessage(
    rawText: string,
    editTurnIndex?: number,
    attachmentsOverride?: PendingAttachment[],
  ) {
    const text = rawText.trim();
    const isEdit = editTurnIndex !== undefined;
    if (
      (!text &&
        !isEdit &&
        pendingAttachments.length === 0 &&
        pendingTextAttachments.length === 0) ||
      sending
    ) {
      // the composer stays typable while a response is in flight (see
      // ChatComposer's isDisabled below) so an Enter press here is a real
      // possibility, not just a stray event - but ChatComposerInput's own
      // Enter-to-submit clears its value unconditionally the moment it
      // calls onSubmit (this function), before it can know sending was
      // actually true. Put the text back instead of silently losing it.
      if (!isEdit && sending) setInput(rawText);
      return;
    }

    if (!isEdit && capabilities.orchestrator) {
      if (text.toLowerCase().startsWith(MULTI_AGENT_PREFIX)) {
        await dispatchMultiAgent(text);
        return;
      }
      if (text === COST_COMMAND) {
        await handleCostCommand();
        return;
      }
      if (text.toLowerCase().startsWith(MODEL_COMMAND_PREFIX)) {
        await handleModelCommand(text);
        return;
      }
      if (text === UNDO_COMMAND) {
        await handleUndoCommand();
        return;
      }
      if (text.toLowerCase().startsWith(REMEMBER_PREFIX)) {
        await handleRememberCommand(text);
        return;
      }
      if (text === COMPACT_COMMAND) {
        await handleCompactCommand();
        return;
      }
      if (text === YOLO_COMMAND) {
        await handleYoloCommand();
        return;
      }
    }

    const requestModel = isEdit ? null : oneShotChatModel;
    const inFlightModel = requestModel ?? effectiveModel;
    if (!isEdit) setOneShotChatModel(null);
    const attachments = isEdit
      ? (attachmentsOverride ?? [])
      : pendingAttachments;
    const textAttachments = isEdit ? [] : pendingTextAttachments;

    const sentImages = attachments
      .filter((a) => !isPdfDataUrl(a.dataUrl))
      .map((a) => a.dataUrl);
    const sentFiles = attachments.filter((a) => isPdfDataUrl(a.dataUrl));

    // text files don't exist as an attachment for the server (see
    // PendingTextAttachment): their content is pasted straight into the
    // message text before it's even displayed - so it's identical when
    // re-read from history, no special reconstruction needed.
    const outgoingText = [
      text,
      ...textAttachments.map(
        (a) => `--- ${a.name} ---\n\`\`\`\n${a.content}\n\`\`\``,
      ),
    ]
      .filter(Boolean)
      .join("\n\n");

    if (!isEdit) {
      setInput("");
      setPendingAttachments([]);
      setPendingTextAttachments([]);
    }

    const startSessionId = sessionId;
    if (displayedSessionIdRef.current === startSessionId) {
      setMessages((prev) => {
        const base = isEdit ? truncateBeforeTurn(prev, editTurnIndex) : prev;
        return [
          ...base,
          {
            kind: "user",
            text: outgoingText,
            time: Date.now(),
            images: sentImages.length ? sentImages : undefined,
            files: sentFiles.length ? sentFiles : undefined,
          },
        ];
      });
    }

    await runChatConversationStream({
      request: {
        session_id: startSessionId,
        message: outgoingText,
        project_id: activeProjectId,
        attachments: attachments.map((attachment) => ({
          name: attachment.name,
          data_url: attachment.dataUrl,
        })),
        edit_turn_index: editTurnIndex ?? null,
        model: requestModel,
      },
      inFlightModel,
      initialSessionId: startSessionId,
      isDisplayed: (targetSessionId) =>
        displayedSessionIdRef.current === targetSessionId,
      updateMessages: setMessages,
      updateSessions: setSessions,
      setSessionCreated: (id) => {
        setSessionId(id);
        localStorage.setItem("triton_session_id", id);
        displayedSessionIdRef.current = id;
      },
      markSending,
      markInFlightModel,
      moveSendingKey,
      setFileRefreshTick,
      addPendingSubagent: (id) => pendingSubagentIdsRef.current.add(id),
      setPendingConfirmation,
      pendingConfirmations: pendingConfirmationsRef.current,
      abortControllers: abortControllersRef.current,
      onStreamEvent: () => {
        if (sseIdleTimerRef.current !== null) clearTimeout(sseIdleTimerRef.current);
        setAwaitingSseEvent(false);
        sseIdleTimerRef.current = setTimeout(() => {
          setAwaitingSseEvent(true);
        }, SSE_IDLE_MS);
      },
      onStreamFinished: () => {
        if (sseIdleTimerRef.current !== null) {
          clearTimeout(sseIdleTimerRef.current);
          sseIdleTimerRef.current = null;
        }
        setAwaitingSseEvent(false);
      },
      refreshSessions: () => {
        void loadSessions();
      },
      notifyCompletion: (text) => {
        notifyIfBackground("Triton a terminé", text);
      },
    });
  }

  useEffect(() => {
    sendMessageRef.current = (text: string) => {
      void sendMessage(text);
    };
  });

  // memoized (useCallback): referenced by cancelMessage below, itself in
  // the escape-key effect's dependencies.
  const respondToConfirmation = useCallback(
    async (approved: boolean, remember = false) => {
      if (!pendingConfirmation) return;
      const { id, sessionId: confirmationSessionId } = pendingConfirmation;
      setPendingConfirmation(null);
      pendingConfirmationsRef.current.delete(confirmationSessionId);

      await fetch(`${API_BASE}/chat/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_id: id, approved, remember }),
      });
    },
    [pendingConfirmation],
  );

  /** Cancels the current (displayed) conversation: closes the client-side SSE
   * stream, tells the server to stop the agentic loop before its next
   * iteration, and rejects any pending tool confirmation so the server
   * isn't left blocked on it until timeout. Memoized (useCallback) since
   * it's referenced in the escape-key effect's dependencies below. */
  const cancelMessage = useCallback(() => {
    if (!sending) return;
    if (pendingConfirmation) {
      void respondToConfirmation(false);
    }
    if (sessionId) {
      void fetch(`${API_BASE}/chat/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
    }
    abortControllersRef.current.get(sessionId ?? "")?.abort();
  }, [sending, pendingConfirmation, sessionId, respondToConfirmation]);

  // escape key cancels the in-flight response, only while one is actually
  // in flight (sending); re-attached on every sessionId change so
  // cancelMessage() always targets the right conversation (matters for a
  // brand-new conversation: sessionId goes from null to its real id on the
  // first SSE event, while sending is already true).
  useEffect(() => {
    if (!sending) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") cancelMessage();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [sending, cancelMessage]);

  // cmd/ctrl+enter for "allow once", cmd/ctrl+shift+enter for "always
  // allow" - same shortcuts as Claude Desktop's own permission prompt
  // (escape = deny already comes from the effect above, cancelMessage
  // rejecting any pending confirmation).
  useEffect(() => {
    if (!pendingConfirmation) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey) || e.key !== "Enter") return;
      e.preventDefault();
      void respondToConfirmation(true, e.shiftKey);
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [pendingConfirmation, respondToConfirmation]);

  // global shortcuts, active everywhere in the app (not just during an
  // in-flight response, unlike escape above): cmd/ctrl+K for search,
  // cmd/ctrl+N for a new conversation.
  useEffect(() => {
    function handleGlobalShortcuts(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key.toLowerCase() === "k") {
        e.preventDefault();
        setView("search");
      } else if (e.key.toLowerCase() === "n") {
        e.preventDefault();
        startNewSession();
      }
    }
    document.addEventListener("keydown", handleGlobalShortcuts);
    return () => {
      document.removeEventListener("keydown", handleGlobalShortcuts);
    };
  }, [startNewSession]);

  // top-level (out-of-project) conversation list as shown in the sidebar
  // (title/content search is its own page - see SearchPage.tsx) - pinned
  // first, stable sort so the natural order (most recent first, already
  // guaranteed by loadSessions) is preserved within each group.
  const topLevelSessions = sessions.filter((s) => s.project_id === null);

  // shows an "empty" assistant message with a loader while no text is
  // arriving yet for this turn. Deliberately NOT excluded when the last
  // message is "tool" (unlike an earlier version that hid it as soon as
  // the first tool call happened): a turn with several tool calls in a row
  // has a real gap between one call ending and the next starting (the
  // model "thinks" again), during which no indicator showed at all - see
  // the "Triton Folder" conversation for an example with 20 back-to-back
  // tool calls and no loader between them. The same gap exists when the
  // last message is assistant text followed by a tool call (e.g. "I'll
  // write X." before a write_file that takes several seconds): the text
  // finishes displaying, no more SSE events arrive while the tool runs,
  // but lastMessage stays "assistant" - awaitingSseEvent (the silence
  // timer, see sendMessage's noteSseEvent) covers this case too, without
  // flickering the loader during an active text stream (tokens arrive much
  // faster than SSE_IDLE_MS).
  const lastMessage = messages[messages.length - 1];
  const showTypingPlaceholder =
    sending &&
    !pendingConfirmation &&
    (lastMessage?.kind !== "assistant" || awaitingSseEvent);
  // THIS conversation's model, once the /model override is factored in -
  // this is what should drive display (badge, avatar, attachment
  // capabilities), not just the global apiModel default.
  const effectiveModel = sessionModelOverride ?? apiModel;
  const displayedInFlightModel = inFlightModels[sessionId ?? ""] ?? effectiveModel;
  const currentModelInfo = modelsCatalog.find((m) => m.id === effectiveModel);
  const supportsImages = currentModelInfo?.supports_images ?? false;
  const supportsFiles = currentModelInfo?.supports_files ?? false;
  // text files (always included in accept) get pasted into the message
  // text rather than sent as a binary attachment (see PendingTextAttachment)
  // - any model understands them, so no need to check
  // supportsImages/supportsFiles for them.
  const attachAccept = [
    supportsImages ? "image/*" : null,
    supportsFiles ? "application/pdf" : null,
    TEXT_ATTACHMENT_EXTENSIONS.join(","),
  ]
    .filter((x): x is string => x !== null)
    .join(",");
  const attachLabel =
    supportsImages && supportsFiles
      ? "Joindre une image, un PDF ou un fichier texte"
      : supportsImages
        ? "Joindre une image ou un fichier texte"
        : supportsFiles
          ? "Joindre un PDF ou un fichier texte"
          : "Joindre un fichier texte";

  // eslint-disable-next-line react-hooks/refs
  const sidebarHeader = SidebarHeader({
    usesMacTitlebarOverlay,
    sidebarCollapsed,
    onToggleSidebar: toggleSidebar,
    onSearch: () => {
      setView("search");
    },
    onNewConversation: startNewSession,
  });

  const sideNavElement = (
    <SideNav
      header={sidebarHeader.header}
      topContent={sidebarHeader.topContent}
    >
      {capabilities.projects && <ProjectSidebarSection
        projects={projects}
        sessions={sessions}
        activeProjectId={activeProjectId}
        activeSessionId={sessionId}
        sendingSessionIds={sendingSessionIds}
        collapsedProjectIds={collapsedProjectIds}
        editingProjectId={editingProjectId}
        editingProjectValue={editingProjectValue}
        editingSessionId={editingSessionId}
        editingValue={editingValue}
        onNewProject={() => {
          setShowProjectForm(true);
        }}
        onToggleCollapse={toggleProjectCollapsed}
        onNewProjectConversation={startProjectSession}
        onStartRenameProject={startRenameProject}
        onDeleteProject={setDeletingProject}
        onEditingProjectValueChange={setEditingProjectValue}
        onCommitRenameProject={(id) => {
          void commitRenameProject(id);
        }}
        onCancelRenameProject={() => {
          setEditingProjectId(null);
        }}
        onSwitchSession={switchSession}
        onStartRenameSession={startRename}
        onTogglePinSession={(session) => {
          void togglePin(session);
        }}
        onDeleteSession={setDeletingSession}
        onEditingValueChange={setEditingValue}
        onCommitRenameSession={(id) => {
          void commitRename(id);
        }}
        onCancelRenameSession={() => {
          setEditingSessionId(null);
        }}
      />}

      {capabilities.subagents && <SubagentsPanel />}

      <ConversationSidebarSection
        sessions={topLevelSessions}
        activeSessionId={sessionId}
        sendingSessionIds={sendingSessionIds}
        editingSessionId={editingSessionId}
        editingValue={editingValue}
        onSwitchSession={switchSession}
        onStartRename={startRename}
        onTogglePin={(session) => {
          void togglePin(session);
        }}
        onDelete={setDeletingSession}
        onEditingValueChange={setEditingValue}
        onCommitRename={(id) => {
          void commitRename(id);
        }}
        onCancelRename={() => {
          setEditingSessionId(null);
        }}
      />
    </SideNav>
  );

  return (
    <Theme theme={neutralTheme} mode={themeMode}>
      <div className="flex h-full min-h-0 flex-col bg-surface">
        {usesMacTitlebarOverlay && (
          <DesktopTitlebar
            sidebarCollapsed={sidebarCollapsed}
            onToggleSidebar={toggleSidebar}
          />
        )}
        <div className="min-h-0 flex-1">
          {sidebarCollapsed && (
            <div
              className={`fixed bottom-0 left-0 z-40 w-2 ${
                usesMacTitlebarOverlay ? "top-[44px]" : "top-0"
              }`}
              onMouseEnter={() => {
                setSidebarPeeking(true);
              }}
            />
          )}
          {sidebarCollapsed && sidebarPeeking && (
            <div
              className={`fixed bottom-0 left-0 z-50 shadow-2xl ${
                usesMacTitlebarOverlay ? "top-[44px]" : "top-0"
              }`}
              onMouseLeave={() => {
                setSidebarPeeking(false);
              }}
            >
              {sideNavElement}
            </div>
          )}
          <AppShell
            variant="elevated"
            height="fill"
            sideNav={sidebarCollapsed ? undefined : sideNavElement}
          >
            {view === "task" && activeTaskId && (
              <TaskView
                key={activeTaskId}
                taskId={activeTaskId}
                onBack={() => {
                  setView("chat");
                }}
              />
            )}
            {view === "search" && (
              <SearchPage
                onBack={() => {
                  setView("chat");
                }}
                onSelectSession={switchSession}
              />
            )}
            {view === "snapshot_history" && sessionId && (
              <SnapshotHistoryView
                key={sessionId}
                sessionId={sessionId}
                onBack={() => {
                  setView("chat");
                }}
                onRestored={() => {
                  setFileRefreshTick((t) => t + 1);
                  setView("chat");
                }}
              />
            )}
            {view === "chat" && (
              <div
                className="relative flex h-full min-h-0"
                onPaste={handlePaste}
                onDragEnter={(e) => {
                  e.preventDefault();
                  setDragDepth((d) => d + 1);
                }}
                onDragLeave={(e) => {
                  e.preventDefault();
                  setDragDepth((d) => Math.max(0, d - 1));
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragDepth(0);
                  handleFilesSelected(e.dataTransfer.files);
                }}
              >
                {dragDepth > 0 && (
                  <div className="pointer-events-none absolute inset-2 z-50 flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed border-accent bg-surface/90">
                    <FileIcon className="h-8 w-8 text-accent" />
                    <Text weight="medium" className="text-accent">
                      Déposer pour joindre
                    </Text>
                  </div>
                )}
                <ChatLayout
                  ref={chatScrollRef}
                  density="spacious"
                  style={{ marginBottom: 52 }}
                  className="min-h-0 min-w-0 flex-1"
                  emptyState={
                    <EmptyState
                      title="Nouvelle conversation"
                      description="Écris un message pour démarrer la conversation."
                    />
                  }
                  scrollButton={
                    <ChatLayoutScrollButton
                      isVisible={showScrollButton}
                      label={hasNewMessage ? "Nouveaux messages" : undefined}
                      onClick={() => {
                        chatScrollRef.current?.scrollTo({
                          top: chatScrollRef.current.scrollHeight,
                          behavior: "smooth",
                        });
                        setHasNewMessage(false);
                      }}
                    />
                  }
                  composer={
                    <ChatComposer
                      value={input}
                      onChange={setInput}
                      onSubmit={(value) => {
                        if (imageMode) {
                          void generateImage(value);
                        } else {
                          void sendMessage(value);
                        }
                      }}
                      onStop={cancelMessage}
                      isStopShown={sending}
                      placeholder={imageMode ? "Décrire l’image à générer…" : "Écrire un message..."}
                      // sending is deliberately NOT here: isDisabled greys the
                      // whole composer out (opacity 0.6) and makes its input
                      // non-editable (contentEditable=false) - there's no
                      // reason typing ahead while a response streams should be
                      // blocked. Actually sending a new message meanwhile is
                      // still guarded inside sendMessage itself. A
                      // confirmation prompt is different: genuinely blocking,
                      // has to be resolved first.
                      isDisabled={!!pendingConfirmation}
                      elevation="none"
                      input={<ChatComposerInput triggers={composerTriggers} />}
                      style={
                        { "--_chat-composer-padding": "24px" } as CSSProperties
                      }
                      drawer={
                        pendingAttachments.length > 0 ||
                        pendingTextAttachments.length > 0 ? (
                          <ChatComposerDrawer
                            count={
                              pendingAttachments.length +
                              pendingTextAttachments.length
                            }
                            label="pièce(s) jointe(s)"
                          >
                            <div className="flex flex-wrap gap-2">
                              {pendingAttachments.map((a, i) =>
                                isPdfDataUrl(a.dataUrl) ? (
                                  <div
                                    key={`${a.name}-${i}`}
                                    className="relative flex h-16 w-32 items-center gap-1.5 rounded-md border border-border px-2"
                                  >
                                    <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                    <Text
                                      size="2xs"
                                      className="min-w-0 truncate"
                                    >
                                      {a.name}
                                    </Text>
                                    <IconButton
                                      label="Retirer"
                                      icon={<XIcon className="h-3 w-3" />}
                                      variant="primary"
                                      size="sm"
                                      className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                      onClick={() => {
                                        removeAttachment(i);
                                      }}
                                    />
                                  </div>
                                ) : (
                                  <div
                                    key={`${a.name}-${i}`}
                                    className="relative"
                                  >
                                    <img
                                      src={a.dataUrl}
                                      alt={a.name}
                                      className="h-16 w-16 rounded-md border border-border object-cover"
                                    />
                                    <IconButton
                                      label="Retirer"
                                      icon={<XIcon className="h-3 w-3" />}
                                      variant="primary"
                                      size="sm"
                                      className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                      onClick={() => {
                                        removeAttachment(i);
                                      }}
                                    />
                                  </div>
                                ),
                              )}
                              {pendingTextAttachments.map((a, i) => (
                                <div
                                  key={`${a.name}-${i}`}
                                  className="relative flex h-16 w-32 items-center gap-1.5 rounded-md border border-border px-2"
                                >
                                  <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                  <Text size="2xs" className="min-w-0 truncate">
                                    {a.name}
                                  </Text>
                                  <IconButton
                                    label="Retirer"
                                    icon={<XIcon className="h-3 w-3" />}
                                    variant="primary"
                                    size="sm"
                                    className="absolute -right-1.5 -top-1.5 h-5 w-5 min-w-0 rounded-full p-0"
                                    onClick={() => {
                                      removeTextAttachment(i);
                                    }}
                                  />
                                </div>
                              ))}
                            </div>
                          </ChatComposerDrawer>
                        ) : undefined
                      }
                      footerActions={
                        <>
                          <input
                            ref={fileInputRef}
                            type="file"
                            accept={imageMode ? "image/*" : attachAccept}
                            multiple
                            className="hidden"
                            onChange={(e) => {
                              handleFilesSelected(e.target.files);
                              e.target.value = "";
                            }}
                          />
                          <IconButton
                            label={imageMode ? "Ajouter une image de référence" : attachLabel}
                            icon={<PlusIcon />}
                            variant="ghost"
                            size="sm"
                            isDisabled={!imageMode && !supportsImages && !supportsFiles}
                            onClick={() => {
                              fileInputRef.current?.click();
                            }}
                          />
                          <IconButton
                            label={imageMode ? "Revenir au chat" : "Générer une image"}
                            icon={<ImageIcon />}
                            variant={imageMode ? "primary" : "ghost"}
                            size="sm"
                            isDisabled={
                              pendingTextAttachments.length > 0 ||
                              pendingAttachments.some((attachment) => isPdfDataUrl(attachment.dataUrl))
                            }
                            onClick={() => {
                              setImageMode((active) => !active);
                            }}
                          />
                        </>
                      }
                      sendActions={
                        <>
                          {yoloEnabled && (
                            <Badge variant="warning" label="YOLO actif" />
                          )}
                          <select
                            key={imageMode ? `image-${imageModel}` : `chat-${effectiveModel}`}
                            aria-label={imageMode ? "Modèle image pour cette génération" : "Modèle chat pour ce message"}
                            value={imageMode ? (oneShotImageModel ?? "") : (oneShotChatModel ?? "")}
                            className="max-w-48 rounded-md border border-border bg-surface px-2 py-1 text-xs text-primary outline-none focus:border-accent"
                            onClick={(event) => {
                              event.stopPropagation();
                            }}
                            onChange={(event) => {
                              if (imageMode) setOneShotImageModel(event.target.value || null);
                              else setOneShotChatModel(event.target.value || null);
                            }}
                          >
                            {imageMode ? (
                              <>
                                <option value="">Par défaut : {imageModel ?? "—"}</option>
                                {imageModelsCatalog.map((model) => (
                                  <option key={model.id} value={model.id}>{model.name}</option>
                                ))}
                              </>
                            ) : (
                              <>
                                <option value="">Conversation : {effectiveModel ?? "—"}</option>
                                {modelsCatalog.map((model) => (
                                  <option key={model.id} value={model.id}>{model.name}</option>
                                ))}
                              </>
                            )}
                          </select>
                          <Badge
                            variant={imageMode ? "warning" : "neutral"}
                            label={
                              imageMode
                                ? oneShotImageModel
                                  ? "Modèle temporaire"
                                  : "Image"
                                : oneShotChatModel
                                  ? "Modèle temporaire"
                                  : effectiveModel ?? "Modèle"
                            }
                          />
                        </>
                      }
                    />
                  }
                >
                  <ChatMessageList isStreaming={sending}>
                    {(() => {
                      const groups = groupMessages(messages);
                      return groups.map((group, gi) => {
                        if (group.type === "user") {
                          const isEditingThis =
                            editingTurnIndex === group.turnIndex;
                          return (
                            <ChatMessage
                              key={gi}
                              sender="user"
                              className="animate-fade-in"
                            >
                              <ChatMessageBubble
                                metadata={
                                  <ChatMessageMetadata
                                    timestamp={
                                      <Timestamp
                                        value={group.msg.time / 1000}
                                        format="time"
                                      />
                                    }
                                    status="sent"
                                    footer={
                                      !isEditingThis && !sending ? (
                                        <button
                                          onClick={() => {
                                            startEditingMessage(
                                              group.turnIndex,
                                              group.msg.text,
                                            );
                                          }}
                                          className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                          title="Modifier"
                                          aria-label="Modifier"
                                        >
                                          <PencilIcon className="h-3.5 w-3.5" />
                                        </button>
                                      ) : undefined
                                    }
                                  />
                                }
                              >
                                {group.msg.images &&
                                  group.msg.images.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-2">
                                      {group.msg.images.map((src, i) => (
                                        <img
                                          key={i}
                                          src={src}
                                          alt=""
                                          className="max-h-48 rounded-md border border-border object-cover"
                                        />
                                      ))}
                                    </div>
                                  )}
                                {group.msg.files &&
                                  group.msg.files.length > 0 && (
                                    <div className="mb-2 flex flex-wrap gap-2">
                                      {group.msg.files.map((f, i) => (
                                        <div
                                          key={i}
                                          className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1"
                                        >
                                          <FileIcon className="h-4 w-4 shrink-0 text-secondary" />
                                          <Text size="2xs">{f.name}</Text>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                {isEditingThis ? (
                                  <div className="flex flex-col gap-2">
                                    <textarea
                                      value={editingText}
                                      onChange={(e) => {
                                        setEditingText(e.target.value);
                                      }}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter" && !e.shiftKey) {
                                          e.preventDefault();
                                          void submitEditedMessage();
                                        } else if (e.key === "Escape") {
                                          cancelEditingMessage();
                                        }
                                      }}
                                      // opened by an explicit user click (not on page load)
                                      autoFocus
                                      rows={Math.min(
                                        8,
                                        editingText.split("\n").length + 1,
                                      )}
                                      className="w-full resize-none rounded-md border border-border bg-transparent p-2 text-sm"
                                    />
                                    <div className="flex justify-end gap-2">
                                      <Button
                                        label="Annuler"
                                        variant="ghost"
                                        size="sm"
                                        onClick={cancelEditingMessage}
                                      />
                                      <Button
                                        label="Renvoyer"
                                        variant="primary"
                                        size="sm"
                                        isDisabled={!editingText.trim()}
                                        onClick={() => {
                                          void submitEditedMessage();
                                        }}
                                      />
                                    </div>
                                  </div>
                                ) : (
                                  group.msg.text
                                )}
                              </ChatMessageBubble>
                            </ChatMessage>
                          );
                        }

                        if (group.type === "system") {
                          return (
                            <ChatSystemMessage
                              key={gi}
                              className="animate-fade-in"
                            >
                              {group.msg.kind === "error" ? (
                                <span className="text-error">
                                  {group.msg.text}
                                </span>
                              ) : (
                                group.msg.text
                              )}
                            </ChatSystemMessage>
                          );
                        }

                        const blocks = toBlocks(group.items);
                        const generatedImages = group.items.flatMap((item) =>
                          item.kind === "assistant" ? item.images ?? [] : [],
                        );
                        const lastItem = group.items[group.items.length - 1];
                        // groupMessages() never creates an "assistant" group with an
                        // empty items array (always at least one initial push) - this
                        // is just a TypeScript guard (noUncheckedIndexedAccess).
                        if (!lastItem)
                          throw new Error("groupe assistant sans element");
                        const lastIsText = lastItem.kind === "assistant";
                        // the model that actually answered in this group (not
                        // necessarily the one currently selected in settings, which
                        // may have changed since) - undefined for history saved before
                        // this field was added, the avatar then falls back
                        // to initials.
                        // A response may contain several assistant fragments
                        // around tool calls. Older saved conversations did
                        // not record `model` on those intermediate fragments,
                        // while the final fragment does have it. Pick any
                        // known model in the group (from the end, which is
                        // normally the final answer) instead of letting one
                        // missing value turn the avatar back into Triton.
                        const groupModel = assistantGroupModel(group.items);
                        const messageAvatar = modelAvatar(groupModel ?? null);

                        return (
                          <ChatMessage
                            key={gi}
                            sender="assistant"
                            className="animate-fade-in"
                            avatar={
                              <Avatar
                                name={messageAvatar.name}
                                src={messageAvatar.logo}
                                size={72}
                                // belt-and-suspenders on top of `size`: last time,
                                // the image (1024x1024 at the source) ended up
                                // rendering at its native size instead of being
                                // constrained to the requested one, overflowing the
                                // whole thread horizontally (no way to scroll it
                                // back). Fixed w-/h- + overflow-hidden on this same
                                // element force a hard cap regardless of the
                                // Avatar component's internal sizing.
                                className="h-[72px] w-[72px] shrink-0 overflow-hidden"
                              />
                            }
                            name="Triton"
                          >
                            {generatedImages.length > 0 && (
                              <div className="mb-3 flex flex-wrap gap-3">
                                {generatedImages.map((src, imageIndex) => (
                                  <button
                                    type="button"
                                    key={`${src.slice(0, 48)}-${imageIndex}`}
                                    className="block overflow-hidden rounded-xl border border-border bg-surface"
                                    title="Agrandir l’image"
                                    onClick={() => {
                                      setPreviewImage(src);
                                    }}
                                  >
                                    <img
                                      src={src}
                                      alt="Image générée"
                                      className="max-h-[32rem] max-w-full object-contain"
                                    />
                                  </button>
                                ))}
                              </div>
                            )}
                            {blocks.map((block, bi) => {
                              // a standalone show_map/show_link_preview (not
                              // grouped with other tool calls, see toBlocks)
                              // renders as a card rather than a collapsible
                              // tool-call line - everything else (including
                              // these two tools when grouped with others)
                              // keeps the generic rendering below.
                              const soleToolCall =
                                block.kind === "tools" &&
                                block.items.length === 1
                                  ? block.items[0]
                                  : undefined;
                              const richCard = soleToolCall
                                ? richCardFromToolCall(
                                    soleToolCall.tool,
                                    soleToolCall.args,
                                  )
                                : null;
                              if (richCard) {
                                return <RichCard key={bi} card={richCard} />;
                              }
                              return block.kind === "tools" ? (
                                <ChatToolCalls
                                  key={bi}
                                  className="animate-fade-in"
                                  defaultIsExpanded
                                  calls={block.items.map((t) => {
                                    const isSubtask =
                                      t.subtaskToolCalls !== undefined;
                                    const status =
                                      t.status ?? toolCallStatus(t.result);
                                    const callCount =
                                      t.subtaskToolCalls?.length ?? 0;
                                    return {
                                      name: t.tool,
                                      status,
                                      node:
                                        isSubtask &&
                                        typeof t.args.model === "string"
                                          ? t.args.model
                                          : t.tool === "web_search"
                                            ? webSearchSource(t.result)
                                            : undefined,
                                      target: isSubtask
                                        ? t.subtaskDescription
                                        : t.tool === "edit_file"
                                          ? editFileTarget(t.args)
                                          : formatArgs(t.args),
                                      stats:
                                        isSubtask &&
                                        status === "running" &&
                                        callCount > 0
                                          ? `${callCount} outil${callCount > 1 ? "s" : ""}`
                                          : undefined,
                                      ...(isSubtask ? {} : toolDiffStats(t)),
                                      resultDetail: isSubtask
                                        ? multiAgentSubtaskDetail(t)
                                        : toolResultDetail(t),
                                    };
                                  })}
                                />
                              ) : block.msg.text ? (
                                <ChatMessageBubble
                                  key={bi}
                                  variant="ghost"
                                  width="100%"
                                  className="animate-fade-in"
                                >
                                  <Markdown>{block.msg.text}</Markdown>
                                </ChatMessageBubble>
                              ) : null;
                            })}
                            <ChatMessageMetadata
                              timestamp={
                                <Timestamp
                                  value={lastItem.time / 1000}
                                  format="time"
                                />
                              }
                              footer={
                                lastIsText && lastItem.text ? (
                                  <div className="inline-flex items-center gap-3">
                                    <button
                                      onClick={() => {
                                        void copyToClipboard(lastItem.text, gi);
                                      }}
                                      className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                      title="Copier"
                                      aria-label="Copier"
                                    >
                                      {copiedIndex === gi ? (
                                        <CheckIcon className="h-3.5 w-3.5" />
                                      ) : (
                                        <CopyIcon className="h-3.5 w-3.5" />
                                      )}
                                    </button>
                                    {/* regenerating only makes sense on the very
                                  last response - regenerating an older one
                                  would overwrite everything after it, not
                                  just that response */}
                                    {gi === groups.length - 1 && !sending && (
                                      <button
                                        onClick={() => {
                                          const userMsg = userMessageAtTurn(
                                            messages,
                                            group.precedingTurnIndex,
                                          );
                                          if (userMsg) {
                                            void regenerateResponse(
                                              group.precedingTurnIndex,
                                              userMsg,
                                            );
                                          }
                                        }}
                                        className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                                        title="Regenerer"
                                        aria-label="Regenerer"
                                      >
                                        <RefreshIcon className="h-3.5 w-3.5" />
                                      </button>
                                    )}
                                  </div>
                                ) : undefined
                              }
                            />
                          </ChatMessage>
                        );
                      });
                    })()}

                    {showTypingPlaceholder && (
                      <ChatMessage
                        sender="assistant"
                        className="animate-fade-in"
                        avatar={
                          <Avatar
                            name={modelAvatar(displayedInFlightModel).name}
                            src={modelAvatar(displayedInFlightModel).logo}
                            size={72}
                            className="h-[72px] w-[72px] shrink-0 overflow-hidden"
                          />
                        }
                        name="Triton"
                      >
                        <ChatMessageBubble variant="ghost" width="100%">
                          <Spinner
                            size="sm"
                            shade="subtle"
                            aria-label="Triton réfléchit"
                          />
                        </ChatMessageBubble>
                      </ChatMessage>
                    )}

                    {pendingConfirmation &&
                      (() => {
                        const { label, server } = parseToolDisplay(
                          pendingConfirmation.tool,
                        );
                        const hasDetails =
                          (pendingConfirmation.tool === "edit_file" &&
                            parseEditFileEdits(pendingConfirmation.args)
                              .length > 0) ||
                          (pendingConfirmation.tool === "write_file" &&
                            !!activeProject &&
                            typeof pendingConfirmation.args.path === "string" &&
                            typeof pendingConfirmation.args.content ===
                              "string") ||
                          Object.keys(pendingConfirmation.args).length > 0;

                        return (
                          <div className="mx-auto flex w-full max-w-sm flex-col items-center gap-4 rounded-2xl border border-border bg-surface px-6 py-6">
                            <Avatar name={server ?? label} size="lg" />

                            <button
                              type="button"
                              disabled={!hasDetails}
                              className="flex items-center gap-1 text-center text-sm disabled:cursor-default"
                              onClick={() => {
                                setConfirmationDetailsExpanded((v) => !v);
                              }}
                            >
                              <span>
                                Triton souhaite utiliser{" "}
                                <strong>{label}</strong>
                                {server && (
                                  <>
                                    {" "}
                                    de <strong>{server}</strong>
                                  </>
                                )}
                                .
                              </span>
                              {hasDetails && (
                                <ChevronRightIcon
                                  className={`h-4 w-4 shrink-0 text-secondary transition-transform ${
                                    confirmationDetailsExpanded
                                      ? "rotate-90"
                                      : ""
                                  }`}
                                />
                              )}
                            </button>

                            {confirmationDetailsExpanded && (
                              <div className="w-full">
                                <Text
                                  size="sm"
                                  color="secondary"
                                  className="mb-2 block break-words text-center"
                                >
                                  {pendingConfirmation.tool === "edit_file"
                                    ? editFileTarget(pendingConfirmation.args)
                                    : formatArgs(pendingConfirmation.args)}
                                </Text>
                                {pendingConfirmation.tool === "edit_file" &&
                                  parseEditFileEdits(pendingConfirmation.args)
                                    .length > 0 && (
                                    <EditFileEdits
                                      edits={parseEditFileEdits(
                                        pendingConfirmation.args,
                                      )}
                                    />
                                  )}
                                {pendingConfirmation.tool === "write_file" &&
                                  activeProject &&
                                  typeof pendingConfirmation.args.path ===
                                    "string" &&
                                  typeof pendingConfirmation.args.content ===
                                    "string" && (
                                    <WriteFileDiff
                                      projectId={activeProject.id}
                                      path={pendingConfirmation.args.path}
                                      newContent={
                                        pendingConfirmation.args.content
                                      }
                                    />
                                  )}
                              </div>
                            )}

                            <div className="flex w-full flex-col gap-2">
                              <Button
                                label="Refuser"
                                variant="ghost"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-border px-1.5 py-0.5 text-xs text-secondary">
                                    Échap
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(false);
                                }}
                              >
                                Refuser
                              </Button>
                              <Button
                                label="Toujours autoriser pour cette conversation"
                                variant="secondary"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-border px-1.5 py-0.5 text-xs text-secondary">
                                    ⇧⌘⏎
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(true, true);
                                }}
                              >
                                Toujours autoriser
                              </Button>
                              <Button
                                label="Autoriser une fois"
                                variant="primary"
                                size="md"
                                className="w-full"
                                endContent={
                                  <kbd className="rounded border border-white/30 px-1.5 py-0.5 text-xs">
                                    ⌘⏎
                                  </kbd>
                                }
                                onClick={() => {
                                  void respondToConfirmation(true);
                                }}
                              >
                                Autoriser une fois
                              </Button>
                            </div>
                          </div>
                        );
                      })()}
                  </ChatMessageList>
                </ChatLayout>
                {capabilities.projects && activeProject && openFile ? (
                  <FileViewerPanel
                    key={`${openFile.projectId}:${openFile.path}`}
                    file={openFile}
                    onClose={() => {
                      setOpenFile(null);
                    }}
                  />
                ) : capabilities.projects && activeProject ? (
                  <ProjectFilePanel
                    projectId={activeProject.id}
                    projectName={activeProject.name}
                    folderPath={activeProject.folder_path}
                    refreshSignal={fileRefreshTick}
                    sessionId={sessionId}
                    onOpenHistory={() => {
                      setView("snapshot_history");
                    }}
                    tasks={backgroundTasks}
                    onOpenTask={openTask}
                    onStopTask={stopTask}
                    onDeleteTask={deleteTask}
                    onOpenFile={setOpenFile}
                    showSnapshots={capabilities.snapshots}
                  />
                ) : (
                  <BackgroundTasksPanel
                    tasks={backgroundTasks}
                    onOpen={openTask}
                    onStop={stopTask}
                    onDelete={deleteTask}
                  />
                )}
              </div>
            )}
          </AppShell>
          {!sidebarCollapsed && (
            <div className="fixed bottom-3 left-0 z-30 flex w-[260px] justify-end gap-0.5 px-2">
              <IconButton
                label="Paramètres"
                icon={<GearIcon />}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSettingsOpen(true);
                }}
              />
              <IconButton
                label={
                  themeMode === "dark"
                    ? "Passer en thème clair"
                    : "Passer en thème sombre"
                }
                icon={themeMode === "dark" ? <MoonIcon /> : <SunIcon />}
                variant="ghost"
                size="sm"
                onClick={toggleTheme}
              />
            </div>
          )}
        </div>
      </div>

      <ImagePreviewDialog
        image={previewImage}
        onOpenChange={(isOpen) => {
          if (!isOpen) setPreviewImage(null);
        }}
        onRequestChange={requestImageChange}
      />

      <AlertDialog
        isOpen={deletingSession !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingSession(null);
        }}
        title="Supprimer la conversation ?"
        description={`« ${deletingSession?.title ?? (deletingSession ? formatSessionLabel(deletingSession.id) : "")} » sera définitivement supprimée. Cette action est irréversible.`}
        actionLabel="Supprimer"
        isActionLoading={isDeleting}
        onAction={confirmDeleteSession}
      />

      {capabilities.projects && <AlertDialog
        isOpen={deletingProject !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingProject(null);
        }}
        title="Supprimer le projet ?"
        description={`« ${deletingProject?.name ?? ""} » sera supprimé. Ses conversations ne seront pas effacées, mais ne seront plus rattachées au dossier.`}
        actionLabel="Supprimer"
        onAction={confirmDeleteProject}
      />}

      {capabilities.snapshots && <AlertDialog
        isOpen={undoTarget !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setUndoTarget(null);
        }}
        title="Annuler le dernier message ?"
        description={`Annule les fichiers créés, modifiés ou supprimés depuis le dernier message écrit dans le dossier du projet. Cette action est irréversible.${describeSnapshotDiff(undoDiff)}`}
        actionLabel="Restaurer"
        isActionLoading={undoing}
        onAction={() => {
          void confirmUndo();
        }}
      />}

      <SettingsModal
        isOpen={settingsOpen}
        onClose={() => {
          setSettingsOpen(false);
        }}
        isWebDeployment={isWebDeployment}
        remoteWorkspacesEnabled={capabilities.remote_workspaces}
        onModelChanged={refreshApiModel}
        onImageModelChanged={refreshImageModel}
      />

      {capabilities.projects && <NewProjectModal
        isOpen={showProjectForm}
        onClose={() => {
          setShowProjectForm(false);
        }}
        onCreated={setProjects}
        isWebDeployment={isWebDeployment}
      />}
    </Theme>
  );
}

export default App;
