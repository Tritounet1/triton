import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import {
    ChatComposer,
    ChatComposerDrawer,
    ChatLayout,
    ChatMessage,
    ChatMessageBubble,
    ChatMessageList,
    ChatMessageMetadata,
    ChatSystemMessage,
    ChatToolCalls,
} from "@astryxdesign/core/Chat";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import {
    SideNav,
    SideNavHeading,
    SideNavItem,
    SideNavSection,
} from "@astryxdesign/core/SideNav";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Theme } from "@astryxdesign/core/theme";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { open as openFolderDialog } from "@tauri-apps/plugin-dialog";
import {
    useCallback,
    useEffect,
    useRef,
    useState,
    type CSSProperties,
    type ReactNode,
} from "react";
import "./App.css";
import { BackgroundTasksPanel } from "./BackgroundTasksPanel";
import { type BackgroundTask } from "./BackgroundTasksSection";
import { formatArgs } from "./format";
import {
    CheckIcon,
    ChevronRightIcon,
    CopyIcon,
    CpuIcon,
    FileIcon,
    FolderIcon,
    GearIcon,
    MoonIcon,
    PencilIcon,
    PlusIcon,
    SearchIcon,
    SunIcon,
    TrashIcon,
    XIcon,
} from "./icons";
import { LogsPage } from "./LogsPage";
import { McpServersPage } from "./McpServersPage";
import { modelAvatar } from "./modelFamilies";
import { ModelPage } from "./ModelPage";
import { notifyIfBackground } from "./notifications";
import { OrchestratorPage } from "./OrchestratorPage";
import { ProjectFilePanel } from "./ProjectFilePanel";
import { SettingsPage } from "./SettingsPage";
import { parseSSE } from "./sse";
import { SubagentsPanel } from "./SubagentsPanel";
import { TaskView } from "./TaskView";

const API_BASE = "http://127.0.0.1:8000";
// en dessous de ce seuil, une reponse est consideree "rapide" : pas de
// notif meme si l'app est en arriere-plan, pour ne pas notifier a chaque
// petit echange.
const LONG_RESPONSE_MS = 15000;
// doit rester alignee avec MAX_ATTACHMENT_BYTES cote serveur (server.py) :
// une image plus grande est rejetee ici avant meme d'etre envoyee.
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

interface SentFile {
  name: string;
  dataUrl: string;
}

type ChatMsg =
  | { kind: "user"; text: string; time: number; images?: string[]; files?: SentFile[] }
  | { kind: "assistant"; text: string; time: number; model?: string }
  | {
      kind: "tool";
      tool: string;
      args: Record<string, unknown>;
      result: string;
      time: number;
    }
  | { kind: "info"; text: string; time: number }
  | { kind: "error"; text: string; time: number };

interface PendingConfirmation {
  id: string;
  tool: string;
  args: Record<string, unknown>;
}

interface PendingAttachment {
  name: string;
  dataUrl: string;
}

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
}

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

interface ContentPart {
  type: "text" | "image_url" | "file";
  text?: string;
  image_url?: { url: string };
  file?: { filename: string; file_data: string };
}

interface RawSessionMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | ContentPart[] | null;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  model?: string;
}

/** Un message utilisateur enregistre peut etre soit une simple chaine, soit
 * une liste de parts (texte + images/fichiers) des qu'une piece jointe a ete
 * envoyee (voir build_user_content cote serveur). */
function extractUserContent(content: string | ContentPart[]): {
  text: string;
  images: string[];
  files: SentFile[];
} {
  if (typeof content === "string") return { text: content, images: [], files: [] };
  const text = content
    .filter((p) => p.type === "text")
    .map((p) => p.text ?? "")
    .join("\n");
  const images = content
    .filter((p) => p.type === "image_url" && p.image_url?.url)
    .map((p) => p.image_url?.url ?? "");
  const files = content
    .filter((p) => p.type === "file" && p.file?.file_data)
    .map((p) => ({ name: p.file?.filename ?? "document.pdf", dataUrl: p.file?.file_data ?? "" }));
  return { text, images, files };
}

function isPdfDataUrl(dataUrl: string): boolean {
  return dataUrl.startsWith("data:application/pdf");
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" */
function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y = "", mo = "", d = "", h = "", mi = ""] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

function historyToMessages(raw: RawSessionMessage[]): ChatMsg[] {
  const out: ChatMsg[] = [];
  const now = Date.now();

  for (const m of raw) {
    if (m.role === "user" && m.content) {
      const { text, images, files } = extractUserContent(m.content);
      out.push({
        kind: "user",
        text,
        time: now,
        images: images.length ? images : undefined,
        files: files.length ? files : undefined,
      });
    } else if (m.role === "assistant") {
      for (const toolCall of m.tool_calls ?? []) {
        const args = JSON.parse(toolCall.function.arguments || "{}") as Record<
          string,
          unknown
        >;
        const toolResult = raw.find(
          (x) => x.role === "tool" && x.tool_call_id === toolCall.id,
        );
        out.push({
          kind: "tool",
          tool: toolCall.function.name,
          args,
          // le contenu d'un message "tool" (resultat d'un appel d'outil)
          // est toujours une chaine simple - seul un message "user" peut
          // contenir une liste de parts (texte + images, voir
          // extractUserContent), d'ou la garde meme si le type partage est
          // plus large.
          result: typeof toolResult?.content === "string" ? toolResult.content : "",
          time: now,
        });
      }
      if (typeof m.content === "string" && m.content) {
        out.push({
          kind: "assistant",
          text: m.content,
          time: now,
          model: m.model,
        });
      }
    }
  }

  return out;
}

type AssistantMsg = Extract<ChatMsg, { kind: "assistant" }>;
type ToolMsg = Extract<ChatMsg, { kind: "tool" }>;

type RenderGroup =
  | { type: "user"; msg: Extract<ChatMsg, { kind: "user" }> }
  | { type: "system"; msg: Extract<ChatMsg, { kind: "info" | "error" }> }
  | { type: "assistant"; items: (AssistantMsg | ToolMsg)[] };

/** Regroupe les messages consécutifs d'assistant/outil sous un seul avatar
 * (comme un vrai fil de discussion), plutôt qu'un avatar répété à chaque
 * morceau de la réponse. */
function groupMessages(msgs: ChatMsg[]): RenderGroup[] {
  const groups: RenderGroup[] = [];
  for (const m of msgs) {
    if (m.kind === "user") {
      groups.push({ type: "user", msg: m });
    } else if (m.kind === "info" || m.kind === "error") {
      groups.push({ type: "system", msg: m });
    } else {
      const last = groups[groups.length - 1];
      if (last?.type === "assistant") {
        last.items.push(m);
      } else {
        groups.push({ type: "assistant", items: [m] });
      }
    }
  }
  return groups;
}

type Block =
  { kind: "tools"; items: ToolMsg[] } | { kind: "text"; msg: AssistantMsg };

/** Dans un groupe assistant, fusionne les appels d'outils consécutifs en un
 * seul ChatToolCalls (résumé repliable natif si plusieurs), sépare le texte. */
function toBlocks(items: (AssistantMsg | ToolMsg)[]): Block[] {
  const blocks: Block[] = [];
  for (const item of items) {
    if (item.kind === "tool") {
      const last = blocks[blocks.length - 1];
      if (last?.kind === "tools") {
        last.items.push(item);
      } else {
        blocks.push({ kind: "tools", items: [item] });
      }
    } else {
      blocks.push({ kind: "text", msg: item });
    }
  }
  return blocks;
}

function toolCallStatus(result: string): "complete" | "error" {
  return result.startsWith("error") || result.startsWith("action denied")
    ? "error"
    : "complete";
}

/** Avant/apres pour un edit_file : construit a partir des arguments de
 * l'appel (old_string/new_string), pas du resultat (juste un message de
 * confirmation) - pas de diff ligne a ligne fine, juste tout l'ancien bloc
 * en rouge puis tout le nouveau en vert, largement suffisant pour voir ce
 * qui a change d'un coup d'oeil. */
function EditFileDiff({
  oldString,
  newString,
}: {
  oldString: string;
  newString: string;
}) {
  return (
    <div className="max-h-64 overflow-y-auto rounded-lg font-mono text-xs">
      {oldString.split("\n").map((line, i) => (
        <div
          key={`old-${i}`}
          className="whitespace-pre bg-error-muted px-2 py-0.5 text-error"
        >
          <span className="select-none opacity-60">- </span>
          {line}
        </div>
      ))}
      {newString.split("\n").map((line, i) => (
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

function toolResultDetail(t: ToolMsg): ReactNode {
  const { old_string: oldString, new_string: newString } = t.args;
  if (
    t.tool === "edit_file" &&
    typeof oldString === "string" &&
    typeof newString === "string"
  ) {
    return <EditFileDiff oldString={oldString} newString={newString} />;
  }
  return (
    <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
      {t.result}
    </pre>
  );
}

function App() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [apiModel, setApiModel] = useState<string | null>(null);
  // catalogue OpenRouter (id + capacites), recupere une fois au demarrage,
  // pour savoir si le modele actuel accepte des images et/ou des PDF
  // (active/desactive et filtre le bouton "joindre" du composer) sans
  // dupliquer cette logique cote serveur.
  const [modelsCatalog, setModelsCatalog] = useState<
    { id: string; supports_images: boolean; supports_files: boolean }[]
  >([]);
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
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
  const [newProjectName, setNewProjectName] = useState("");
  const [newProjectFolder, setNewProjectFolder] = useState("");
  const [creatingProject, setCreatingProject] = useState(false);
  const [projectFormError, setProjectFormError] = useState<string | null>(null);
  const [deletingProject, setDeletingProject] = useState<Project | null>(null);
  const [collapsedProjectIds, setCollapsedProjectIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [fileRefreshTick, setFileRefreshTick] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  // ids des conversations dont le CONTENU (pas le titre, deja filtre
  // instantanement cote client) correspond a la recherche - remplis avec
  // un delai via /sessions/search, qui lit les fichiers de session cote
  // serveur plutot que de rapatrier tout l'historique de chaque
  // conversation juste pour la filtrer.
  const [contentMatchIds, setContentMatchIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [pendingConfirmation, setPendingConfirmation] =
    useState<PendingConfirmation | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  // ids des sous-agents dispatches dans la conversation ACTIVE (remis a
  // zero au changement de conversation) : permet de relancer le modele
  // automatiquement une fois l'un d'eux termine, plutot que de rester en
  // attente indefiniment d'un nouveau message de l'utilisateur.
  const pendingSubagentIdsRef = useRef<Set<string>>(new Set());
  // tenues a jour apres chaque rendu (effet sans tableau de dependances),
  // lues depuis un minuteur autonome (setInterval) plutot qu'une fermeture
  // figee sur le rendu ou l'effet a demarre : evite de redemarrer ce
  // minuteur a chaque frappe/changement d'etat, cf. cancelMessage/
  // useCallback plus haut pour le meme probleme. Mutation directe pendant
  // le rendu interdite par react-hooks/refs, d'ou l'effet.
  const sendingRef = useRef(sending);
  const inputRef = useRef(input);
  const sendMessageRef = useRef((_text: string): void => undefined);
  useEffect(() => {
    sendingRef.current = sending;
    inputRef.current = input;
    sendMessageRef.current = (text: string) => {
      void sendMessage(text);
    };
  });
  const [themeMode, setThemeMode] = useState<"light" | "dark">(() =>
    localStorage.getItem("triton_theme") === "light" ? "light" : "dark",
  );
  const [view, setView] = useState<
    "chat" | "settings" | "logs" | "mcp" | "model" | "task" | "orchestrator"
  >("chat");
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

  function loadSessions() {
    fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Session[]) => {
        setSessions([...list].reverse());
      })
      .catch(() => {
        // API hors ligne ou requete echouee : la sidebar reste vide, sans casser l'app
      });
  }

  function loadProjects() {
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Project[]) => {
        setProjects(list);
      })
      .catch(() => {
        // API hors ligne ou requete echouee : la liste de projets reste vide
      });
  }

  async function pickProjectFolder() {
    const folder = await openFolderDialog({ directory: true, multiple: false });
    if (typeof folder === "string") setNewProjectFolder(folder);
  }

  function resetProjectForm() {
    setNewProjectName("");
    setNewProjectFolder("");
    setProjectFormError(null);
    setShowProjectForm(false);
  }

  async function submitNewProject() {
    if (!newProjectName.trim() || !newProjectFolder.trim()) {
      setProjectFormError("le nom et le dossier sont obligatoires.");
      return;
    }
    setCreatingProject(true);
    setProjectFormError(null);

    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: newProjectName.trim(),
          folder_path: newProjectFolder.trim(),
        }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as {
          detail?: string;
        } | null;
        setProjectFormError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      setProjects((await res.json()) as Project[]);
      resetProjectForm();
    } catch {
      setProjectFormError(
        "impossible de contacter l'API Triton (127.0.0.1:8000).",
      );
    } finally {
      setCreatingProject(false);
    }
  }

  async function confirmDeleteProject() {
    if (!deletingProject) return;
    const id = deletingProject.id;
    setDeletingProject(null);

    const res = await fetch(`${API_BASE}/projects/${id}`, { method: "DELETE" });
    if (res.ok) {
      setProjects((await res.json()) as Project[]);
      if (activeProjectId === id) setActiveProjectId(null);
      loadSessions();
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
        // session introuvable cote serveur : on garde l'historique local tel quel
      });
  }

  useEffect(() => {
    refreshApiModel();

    fetch(`${API_BASE}/openrouter/models`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: { id: string; supports_images: boolean; supports_files: boolean }[]) => {
        setModelsCatalog(data);
      })
      .catch(() => {
        // API OpenRouter injoignable : le bouton "joindre" reste desactive
      });

    loadSessions();
    loadProjects();

    // uniquement au demarrage, pour une session deja connue (localStorage) ;
    // ne doit pas se redeclencher quand sendMessage() fixe sessionId lui-meme,
    // sinon ca part en course avec le streaming en cours.
    const stored = localStorage.getItem("triton_session_id");
    if (stored) loadHistory(stored);
  }, []);

  // relance automatiquement le modele une fois qu'un sous-agent dispatche
  // dans la conversation active se termine : sans ca, le tour se termine
  // des que le modele repond en texte (pas d'appel d'outil) et plus rien ne
  // le fait revenir verifier le resultat tant que l'utilisateur n'envoie
  // pas un nouveau message. Lit sending/input via des refs (tenues a jour
  // a chaque rendu plus haut) plutot que de redemarrer ce minuteur a chaque
  // frappe/etat.
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
          // API hors ligne : nouvelle tentative au prochain intervalle
        });
    }, 4000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  // taches en arriere-plan (start_background_task) de la conversation
  // active : affichees dans le panneau lateral droit (BackgroundTasksPanel /
  // ProjectFilePanel), quel que soit le view courant, pour rester "vite
  // accessibles" pendant que le modele travaille dans la conversation.
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    function load() {
      fetch(`${API_BASE}/background_tasks?session_id=${sessionId}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((data: BackgroundTask[]) => {
          if (!cancelled) setBackgroundTasks(data);
        })
        .catch(() => {
          // API hors ligne : nouvelle tentative au prochain intervalle
        });
    }
    load();
    const interval = setInterval(load, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId]);

  function openTask(id: string) {
    setActiveTaskId(id);
    setView("task");
  }

  function stopTask(id: string) {
    fetch(`${API_BASE}/background_tasks/${id}/stop`, { method: "POST" }).catch(() => {
      // API hors ligne : le prochain polling reflete quand meme l'etat reel
    });
  }

  function deleteTask(id: string) {
    setBackgroundTasks((prev) => prev.filter((t) => t.id !== id));
    fetch(`${API_BASE}/background_tasks/${id}`, { method: "DELETE" }).catch(() => {
      // API hors ligne : le prochain polling la fera reapparaitre si la
      // suppression n'a en fait pas eu lieu cote serveur
    });
  }

  function switchSession(id: string) {
    setView("chat");
    if (id === sessionId || sending) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    setActiveProjectId(sessions.find((s) => s.id === id)?.project_id ?? null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
    loadHistory(id);
  }

  function startNewSession() {
    setView("chat");
    if (sending) return;
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(null);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
  }

  function startProjectSession(projectId: string) {
    setView("chat");
    if (sending) return;
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(projectId);
    pendingSubagentIdsRef.current.clear();
    setBackgroundTasks([]);
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

  function handleFilesSelected(fileList: FileList | null) {
    if (!fileList) return;
    for (const file of Array.from(fileList)) {
      const isImage = file.type.startsWith("image/");
      const isPdf = file.type === "application/pdf";
      if ((isImage && !supportsImages) || (isPdf && !supportsFiles) || (!isImage && !isPdf)) {
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
        setPendingAttachments((prev) => [...prev, { name: file.name, dataUrl }]);
      };
      reader.readAsDataURL(file);
    }
  }

  function removeAttachment(index: number) {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== index));
  }

  async function copyToClipboard(text: string, index: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => {
      setCopiedIndex((current) => (current === index ? null : current));
    }, 1500);
  }

  async function sendMessage(rawText: string) {
    const text = rawText.trim();
    if ((!text && pendingAttachments.length === 0) || sending) return;

    const startTime = performance.now();
    const attachments = pendingAttachments;

    const sentImages = attachments.filter((a) => !isPdfDataUrl(a.dataUrl)).map((a) => a.dataUrl);
    const sentFiles = attachments.filter((a) => isPdfDataUrl(a.dataUrl));

    setInput("");
    setPendingAttachments([]);
    setMessages((prev) => [
      ...prev,
      {
        kind: "user",
        text,
        time: Date.now(),
        images: sentImages.length ? sentImages : undefined,
        files: sentFiles.length ? sentFiles : undefined,
      },
    ]);
    setSending(true);

    // suivi local plutot que l'etat React sessionId : ce dernier reste sur sa
    // valeur de depart (fermeture) le temps de tout le for-await, alors que
    // l'evenement "session" peut arriver avec un nouvel id des la premiere
    // ligne du flux, pour une toute nouvelle conversation.
    let currentSessionId = sessionId;
    let assistantText = "";
    let flushScheduled = false;

    // les tokens peuvent arriver bien plus vite que le rythme d'affichage
    // utile : on regroupe les mises a jour par frame plutot que d'en
    // declencher une a chaque morceau de texte recu. L'updater ne doit
    // dependre que de `prev` (pas d'un index externe mute a l'interieur),
    // sinon React (StrictMode rejoue les updaters pour verifier qu'ils sont
    // purs) plante au second passage avec un index deja decale.
    function scheduleFlush() {
      if (flushScheduled) return;
      flushScheduled = true;
      requestAnimationFrame(() => {
        flushScheduled = false;
        const textSoFar = assistantText;
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.kind === "assistant") {
            return [...prev.slice(0, -1), { ...last, text: textSoFar }];
          }
          return [
            ...prev,
            { kind: "assistant", text: textSoFar, time: Date.now() },
          ];
        });
      });
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          message: text,
          project_id: activeProjectId,
          attachments: attachments.map((a) => ({ name: a.name, data_url: a.dataUrl })),
        }),
        signal: controller.signal,
      });

      for await (const { event, data } of parseSSE(res)) {
        switch (event) {
          case "session": {
            const id = data.session_id as string;
            currentSessionId = id;
            if (id !== sessionId) {
              setSessionId(id);
              localStorage.setItem("triton_session_id", id);
            }
            break;
          }
          case "title": {
            const title = data.title as string;
            // le serveur envoie toujours l'evenement "session" avant "title"
            // (voir run_chat_stream dans server.py) : currentSessionId est deja defini ici
            if (!currentSessionId) break;
            const id = currentSessionId;
            setSessions((prev) =>
              prev.some((s) => s.id === id)
                ? prev.map((s) => (s.id === id ? { ...s, title } : s))
                : [{ id, title, project_id: activeProjectId }, ...prev],
            );
            break;
          }
          case "token": {
            assistantText += data.text as string;
            scheduleFlush();
            break;
          }
          case "tool_call": {
            setMessages((prev) => [
              ...prev,
              {
                kind: "tool",
                tool: data.tool as string,
                args: data.args as Record<string, unknown>,
                result: data.result as string,
                time: Date.now(),
              },
            ]);
            assistantText = "";
            // un outil a pu modifier le systeme de fichiers (write_file,
            // edit_file, run_shell...) : rafraichit le panneau de fichiers
            // du projet actif, si affiche. Sans filtrer par nom d'outil
            // (couvre aussi les outils MCP) : une requete GET en trop est
            // negligeable.
            setFileRefreshTick((t) => t + 1);
            if (data.tool === "dispatch_subagent") {
              const match = /\(id=([a-f0-9]+)\)/.exec(
                (data.result as string) || "",
              );
              if (match?.[1]) pendingSubagentIdsRef.current.add(match[1]);
            }
            break;
          }
          case "done": {
            // rattache le modele qui a repondu au dernier message assistant
            // (pour l'avatar), et reconcilie son texte avec la version
            // finale envoyee par le serveur au cas ou il manquerait un
            // morceau (ex. le dernier flush programme n'a pas encore tourne).
            const model = data.model as string;
            const content = data.content as string;
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              if (last?.kind === "assistant") {
                return [
                  ...prev.slice(0, -1),
                  { ...last, text: content || last.text, model },
                ];
              }
              return [
                ...prev,
                { kind: "assistant", text: content, time: Date.now(), model },
              ];
            });
            break;
          }
          case "confirmation_required": {
            setPendingConfirmation({
              id: data.confirmation_id as string,
              tool: data.tool as string,
              args: data.args as Record<string, unknown>,
            });
            break;
          }
          case "info": {
            setMessages((prev) => [
              ...prev,
              { kind: "info", text: data.message as string, time: Date.now() },
            ]);
            break;
          }
          case "error": {
            setMessages((prev) => [
              ...prev,
              { kind: "error", text: data.message as string, time: Date.now() },
            ]);
            break;
          }
          default:
            break;
        }
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        const finalText = assistantText
          ? `${assistantText}\n\n*(interrompu)*`
          : "*(interrompu)*";
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.kind === "assistant") {
            return [...prev.slice(0, -1), { ...last, text: finalText }];
          }
          return [
            ...prev,
            { kind: "assistant", text: finalText, time: Date.now() },
          ];
        });
      } else {
        console.error("erreur pendant l'échange avec l'API Triton :", err);
        setMessages((prev) => [
          ...prev,
          {
            kind: "error",
            text: "impossible de contacter l'API Triton (127.0.0.1:8000).",
            time: Date.now(),
          },
        ]);
      }
    } finally {
      abortControllerRef.current = null;
      setPendingConfirmation(null);
      setSending(false);
      loadSessions();

      if (performance.now() - startTime > LONG_RESPONSE_MS) {
        notifyIfBackground(
          "Triton a terminé",
          assistantText ? assistantText.slice(0, 200) : "La réponse est prête.",
        );
      }
    }
  }

  // memoisee (useCallback) : referencee par cancelMessage ci-dessous, elle
  // meme dans les dependances de l'effet echap.
  const respondToConfirmation = useCallback(
    async (approved: boolean, remember = false) => {
      if (!pendingConfirmation) return;
      const { id } = pendingConfirmation;
      setPendingConfirmation(null);

      await fetch(`${API_BASE}/chat/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirmation_id: id, approved, remember }),
      });
    },
    [pendingConfirmation],
  );

  /** Interrompt la conversation en cours : ferme le flux SSE cote client,
   * signale au serveur d'arreter la boucle agentique avant sa prochaine
   * iteration, et refuse une confirmation d'outil eventuellement en attente
   * pour ne pas laisser le serveur bloque dessus jusqu'au timeout. Memoisee
   * (useCallback) car referencee dans les dependances de l'effet echap
   * ci-dessous. */
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
    abortControllerRef.current?.abort();
  }, [sending, pendingConfirmation, sessionId, respondToConfirmation]);

  // touche echap pour interrompre la reponse en cours, tant qu'une reponse
  // est effectivement en cours (sending) ; reattache a chaque changement de
  // sessionId pour que cancelMessage() cible toujours la bonne conversation
  // (utile pour une toute nouvelle conversation : sessionId passe de null a
  // son id reel des le premier evenement SSE, pendant que sending est deja true).
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

  // recherche dans le CONTENU des messages (le titre est deja filtre
  // instantanement cote client dans filteredSessions ci-dessous) : debounce
  // de 300ms pour ne pas relire tous les fichiers de session a chaque
  // frappe. setContentMatchIds() reste dans le callback du timeout (jamais
  // synchrone dans le corps de l'effet), y compris pour la remise a vide.
  useEffect(() => {
    const query = search.trim();
    const timeout = setTimeout(() => {
      if (!query) {
        setContentMatchIds(new Set());
        return;
      }
      fetch(`${API_BASE}/sessions/search?q=${encodeURIComponent(query)}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((ids: string[]) => {
          setContentMatchIds(new Set(ids));
        })
        .catch(() => {
          // API hors ligne : pas de resultats bases sur le contenu, la
          // recherche par titre (instantanee) continue de fonctionner
        });
    }, 300);
    return () => {
      clearTimeout(timeout);
    };
  }, [search]);

  const filteredSessions = sessions.filter((s) => {
    if (s.project_id !== null) return false;
    if (!search) return true;
    const titleMatches = (s.title ?? formatSessionLabel(s.id))
      .toLowerCase()
      .includes(search.toLowerCase());
    return titleMatches || contentMatchIds.has(s.id);
  });

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;
  // affiche un message assistant "vide" avec un loader tant que rien n'est
  // encore arrive pour ce tour (ni texte, ni tool_call) : une fois le
  // premier evenement traite, le dernier message devient "assistant" ou
  // "tool" et ce placeholder disparait de lui-meme.
  const lastMessage = messages[messages.length - 1];
  const showTypingPlaceholder =
    sending &&
    !pendingConfirmation &&
    lastMessage?.kind !== "assistant" &&
    lastMessage?.kind !== "tool";
  const currentModelInfo = modelsCatalog.find((m) => m.id === apiModel);
  const supportsImages = currentModelInfo?.supports_images ?? false;
  const supportsFiles = currentModelInfo?.supports_files ?? false;
  const attachAccept = [supportsImages ? "image/*" : null, supportsFiles ? "application/pdf" : null]
    .filter((x): x is string => x !== null)
    .join(",");
  const attachLabel =
    supportsImages && supportsFiles
      ? "Joindre une image ou un PDF"
      : supportsImages
        ? "Joindre une image"
        : supportsFiles
          ? "Joindre un PDF"
          : "Le modèle actuel ne prend pas de pièces jointes";

  return (
    <Theme theme={neutralTheme} mode={themeMode}>
      <AppShell
        variant="elevated"
        height="fill"
        sideNav={
          <SideNav
            header={
              <SideNavHeading
                heading="Triton"
                icon={<Avatar src="triton-logo.jpeg" name="Triton" size="xsm" />}
              />
            }
            topContent={
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-1">
                  <Button
                    label="Nouvelle conversation"
                    icon={<PlusIcon />}
                    variant="secondary"
                    size="sm"
                    onClick={startNewSession}
                    className="flex-1 justify-start"
                  />
                  <IconButton
                    label="Rechercher"
                    icon={<SearchIcon />}
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setSearchOpen((v) => !v);
                    }}
                  />
                </div>
                {searchOpen && (
                  <TextInput
                    value={search}
                    onChange={setSearch}
                    placeholder="Titre ou contenu..."
                    isLabelHidden
                    label="Rechercher une conversation, par titre ou par contenu"
                    size="sm"
                    hasAutoFocus
                  />
                )}
                <div className="flex items-center gap-1">
                  <Button
                    label="Retour au mode normal"
                    variant={view === "orchestrator" ? "ghost" : "secondary"}
                    size="sm"
                    onClick={() => {
                      setView("chat");
                    }}
                    className="flex-1 justify-center"
                  >
                    Normal
                  </Button>
                  <Button
                    label="Passer en mode multi-agent"
                    icon={<CpuIcon />}
                    variant={view === "orchestrator" ? "secondary" : "ghost"}
                    size="sm"
                    onClick={() => {
                      setView("orchestrator");
                    }}
                    className="flex-1 justify-center"
                  >
                    Multi-agent
                  </Button>
                </div>
              </div>
            }
            footer={
              <div className="flex items-center justify-end gap-0.5 px-1 py-1">
                <IconButton
                  label="Paramètres"
                  icon={<GearIcon />}
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setView("settings");
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
            }
          >
            <SideNavSection
              title="Projets"
              endContent={
                <IconButton
                  label="Nouveau projet"
                  icon={<PlusIcon />}
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setShowProjectForm((v) => !v);
                  }}
                />
              }
            >
              {showProjectForm && (
                <div className="flex flex-col gap-2 px-2 py-1">
                  <TextInput
                    value={newProjectName}
                    onChange={setNewProjectName}
                    placeholder="Nom du projet"
                    isLabelHidden
                    label="Nom du projet"
                    size="sm"
                    hasAutoFocus
                  />
                  <Button
                    label={newProjectFolder || "Choisir un dossier..."}
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      void pickProjectFolder();
                    }}
                    className="justify-start truncate"
                  />
                  {projectFormError && (
                    <Text size="2xs" className="text-error">
                      {projectFormError}
                    </Text>
                  )}
                  <div className="flex gap-1">
                    <Button
                      label="Créer"
                      variant="primary"
                      size="sm"
                      isLoading={creatingProject}
                      onClick={() => {
                        void submitNewProject();
                      }}
                      className="flex-1"
                    />
                    <Button
                      label="Annuler"
                      variant="ghost"
                      size="sm"
                      onClick={resetProjectForm}
                    />
                  </div>
                </div>
              )}
              {projects.length === 0 && !showProjectForm && (
                <Text size="2xs" color="secondary" className="block px-2 py-1">
                  Aucun projet.
                </Text>
              )}
              {projects.map((p) => {
                const isCollapsed = collapsedProjectIds.has(p.id);
                return (
                  <div key={p.id}>
                    {editingProjectId === p.id ? (
                      <div className="px-2 py-1">
                        <TextInput
                          value={editingProjectValue}
                          onChange={setEditingProjectValue}
                          isLabelHidden
                          label="Nom du projet"
                          size="sm"
                          hasAutoFocus
                          onEnter={() => {
                            void commitRenameProject(p.id);
                          }}
                          onBlur={() => {
                            void commitRenameProject(p.id);
                          }}
                          onKeyDown={(e) => {
                            if (e.key === "Escape") setEditingProjectId(null);
                          }}
                        />
                      </div>
                    ) : (
                      <SideNavItem
                        label={p.name}
                        icon={<FolderIcon className="h-4 w-4" />}
                        isSelected={
                          p.id === activeProjectId && sessionId === null
                        }
                        onClick={() => {
                          toggleProjectCollapsed(p.id);
                        }}
                        endContent={
                          <div className="flex items-center gap-0.5">
                            <IconButton
                              label="Nouvelle conversation dans ce projet"
                              icon={<PlusIcon />}
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                startProjectSession(p.id);
                              }}
                            />
                            <IconButton
                              label="Renommer le projet"
                              icon={<PencilIcon />}
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                startRenameProject(p);
                              }}
                            />
                            <IconButton
                              label="Supprimer le projet"
                              icon={<TrashIcon />}
                              variant="ghost"
                              size="sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                setDeletingProject(p);
                              }}
                            />
                            <ChevronRightIcon
                              className={`h-4 w-4 shrink-0 text-secondary transition-transform ${isCollapsed ? "" : "rotate-90"}`}
                            />
                          </div>
                        }
                      />
                    )}
                    {!isCollapsed &&
                      sessions
                        .filter((s) => s.project_id === p.id)
                        .map((s) =>
                          editingSessionId === s.id ? (
                            <div key={s.id} className="py-1 pl-4">
                              <TextInput
                                value={editingValue}
                                onChange={setEditingValue}
                                isLabelHidden
                                label="Titre de la conversation"
                                size="sm"
                                hasAutoFocus
                                onEnter={() => {
                                  void commitRename(s.id);
                                }}
                                onBlur={() => {
                                  void commitRename(s.id);
                                }}
                                onKeyDown={(e) => {
                                  if (e.key === "Escape")
                                    setEditingSessionId(null);
                                }}
                              />
                            </div>
                          ) : (
                            <SideNavItem
                              key={s.id}
                              label={s.title ?? formatSessionLabel(s.id)}
                              isSelected={s.id === sessionId}
                              onClick={() => {
                                switchSession(s.id);
                              }}
                              className="pl-4"
                              endContent={
                                <div className="flex items-center gap-0.5">
                                  <IconButton
                                    label="Renommer"
                                    icon={<PencilIcon />}
                                    variant="ghost"
                                    size="sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      startRename(s);
                                    }}
                                  />
                                  <IconButton
                                    label="Supprimer"
                                    icon={<TrashIcon />}
                                    variant="ghost"
                                    size="sm"
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      setDeletingSession(s);
                                    }}
                                  />
                                </div>
                              }
                            />
                          ),
                        )}
                  </div>
                );
              })}
            </SideNavSection>

            <SubagentsPanel />

            <SideNavSection title="Conversations">
              {filteredSessions.length === 0 && (
                <Text size="2xs" color="secondary" className="block px-2 py-1">
                  Aucune conversation.
                </Text>
              )}
              {filteredSessions.map((s) =>
                editingSessionId === s.id ? (
                  <div key={s.id} className="px-2 py-1">
                    <TextInput
                      value={editingValue}
                      onChange={setEditingValue}
                      isLabelHidden
                      label="Titre de la conversation"
                      size="sm"
                      hasAutoFocus
                      onEnter={() => {
                        void commitRename(s.id);
                      }}
                      onBlur={() => {
                        void commitRename(s.id);
                      }}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setEditingSessionId(null);
                      }}
                    />
                  </div>
                ) : (
                  <SideNavItem
                    key={s.id}
                    label={s.title ?? formatSessionLabel(s.id)}
                    isSelected={s.id === sessionId}
                    onClick={() => {
                      switchSession(s.id);
                    }}
                    endContent={
                      <div className="flex items-center gap-0.5">
                        <IconButton
                          label="Renommer"
                          icon={<PencilIcon />}
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            startRename(s);
                          }}
                        />
                        <IconButton
                          label="Supprimer"
                          icon={<TrashIcon />}
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            setDeletingSession(s);
                          }}
                        />
                      </div>
                    }
                  />
                ),
              )}
            </SideNavSection>
          </SideNav>
        }
      >
        {view === "settings" && (
          <SettingsPage
            onBack={() => {
              setView("chat");
            }}
            onOpenLogs={() => {
              setView("logs");
            }}
            onOpenMcp={() => {
              setView("mcp");
            }}
            onOpenModel={() => {
              setView("model");
            }}
          />
        )}
        {view === "logs" && (
          <LogsPage
            onBack={() => {
              setView("settings");
            }}
          />
        )}
        {view === "mcp" && (
          <McpServersPage
            onBack={() => {
              setView("settings");
            }}
          />
        )}
        {view === "model" && (
          <ModelPage
            onBack={() => {
              refreshApiModel();
              setView("settings");
            }}
          />
        )}
        {view === "task" && activeTaskId && (
          <TaskView
            key={activeTaskId}
            taskId={activeTaskId}
            onBack={() => {
              setView("chat");
            }}
          />
        )}
        {view === "orchestrator" && (
          <OrchestratorPage
            onBack={() => {
              setView("chat");
            }}
          />
        )}
        {view === "chat" && (
          <div className="flex h-full">
            <ChatLayout
              density="spacious"
              className="h-full min-w-0 flex-1"
              emptyState={
                <EmptyState
                  title="Nouvelle conversation"
                  description="Écris un message pour démarrer la conversation."
                />
              }
              composer={
                <ChatComposer
                  value={input}
                  onChange={setInput}
                  onSubmit={(value) => {
                    void sendMessage(value);
                  }}
                  onStop={cancelMessage}
                  isStopShown={sending}
                  placeholder="Écrire un message..."
                  isDisabled={sending || !!pendingConfirmation}
                  density="compact"
                  elevation="none"
                  style={
                    { "--_chat-composer-padding": "24px" } as CSSProperties
                  }
                  drawer={
                    pendingAttachments.length > 0 ? (
                      <ChatComposerDrawer count={pendingAttachments.length} label="pièce(s) jointe(s)">
                        <div className="flex flex-wrap gap-2">
                          {pendingAttachments.map((a, i) =>
                            isPdfDataUrl(a.dataUrl) ? (
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
                                  onClick={() => { removeAttachment(i); }}
                                />
                              </div>
                            ) : (
                              <div key={`${a.name}-${i}`} className="relative">
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
                                  onClick={() => { removeAttachment(i); }}
                                />
                              </div>
                            ),
                          )}
                        </div>
                      </ChatComposerDrawer>
                    ) : undefined
                  }
                  footerActions={
                    <>
                      <input
                        ref={fileInputRef}
                        type="file"
                        accept={attachAccept}
                        multiple
                        className="hidden"
                        onChange={(e) => {
                          handleFilesSelected(e.target.files);
                          e.target.value = "";
                        }}
                      />
                      <IconButton
                        label={attachLabel}
                        icon={<PlusIcon />}
                        variant="ghost"
                        size="sm"
                        isDisabled={!supportsImages && !supportsFiles}
                        onClick={() => { fileInputRef.current?.click(); }}
                      />
                    </>
                  }
                  sendActions={
                    apiModel ? <Badge variant="neutral" label={apiModel} /> : undefined
                  }
                />
              }
            >
              <ChatMessageList isStreaming={sending}>
                {groupMessages(messages).map((group, gi) => {
                  if (group.type === "user") {
                    return (
                      <ChatMessage key={gi} sender="user">
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
                            />
                          }
                        >
                          {group.msg.images && group.msg.images.length > 0 && (
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
                          {group.msg.files && group.msg.files.length > 0 && (
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
                          {group.msg.text}
                        </ChatMessageBubble>
                      </ChatMessage>
                    );
                  }

                  if (group.type === "system") {
                    return (
                      <ChatSystemMessage key={gi}>
                        {group.msg.kind === "error" ? (
                          <span className="text-error">{group.msg.text}</span>
                        ) : (
                          group.msg.text
                        )}
                      </ChatSystemMessage>
                    );
                  }

                  const blocks = toBlocks(group.items);
                  const lastItem = group.items[group.items.length - 1];
                  // groupMessages() ne cree jamais un groupe "assistant" avec un
                  // tableau items vide (toujours au moins un push initial) : ceci
                  // n'est qu'un garde-fou pour TypeScript (noUncheckedIndexedAccess).
                  if (!lastItem)
                    throw new Error("groupe assistant sans element");
                  const lastIsText = lastItem.kind === "assistant";
                  // le modele qui a effectivement repondu dans ce groupe (pas
                  // forcement celui actuellement selectionne dans les parametres,
                  // qui a pu changer depuis) ; undefined pour un historique
                  // enregistre avant l'ajout de ce champ, l'avatar retombe alors
                  // sur les initiales.
                  const groupModel = group.items.find(
                    (it): it is AssistantMsg => it.kind === "assistant",
                  )?.model;
                  const messageAvatar = modelAvatar(groupModel ?? null);

                  return (
                    <ChatMessage
                      key={gi}
                      sender="assistant"
                      avatar={
                        <Avatar
                          name={messageAvatar.name}
                          src={messageAvatar.logo}
                          size="sm"
                        />
                      }
                      name="Triton"
                    >
                      {blocks.map((block, bi) =>
                        block.kind === "tools" ? (
                          <ChatToolCalls
                            key={bi}
                            calls={block.items.map((t) => ({
                              name: t.tool,
                              status: toolCallStatus(t.result),
                              target: formatArgs(t.args),
                              resultDetail: toolResultDetail(t),
                            }))}
                          />
                        ) : (
                          <ChatMessageBubble
                            key={bi}
                            variant="ghost"
                            width="100%"
                          >
                            <Markdown>{block.msg.text}</Markdown>
                          </ChatMessageBubble>
                        ),
                      )}
                      <ChatMessageMetadata
                        timestamp={
                          <Timestamp
                            value={lastItem.time / 1000}
                            format="time"
                          />
                        }
                        footer={
                          lastIsText && lastItem.text ? (
                            <button
                              onClick={() => {
                                void copyToClipboard(lastItem.text, gi);
                              }}
                              className="inline-flex items-center gap-1 text-secondary hover:text-primary"
                              title="Copier"
                            >
                              {copiedIndex === gi ? (
                                <CheckIcon className="h-3.5 w-3.5" />
                              ) : (
                                <CopyIcon className="h-3.5 w-3.5" />
                              )}
                            </button>
                          ) : undefined
                        }
                      />
                    </ChatMessage>
                  );
                })}

                {showTypingPlaceholder && (
                  <ChatMessage
                    sender="assistant"
                    avatar={
                      <Avatar
                        name={modelAvatar(apiModel).name}
                        src={modelAvatar(apiModel).logo}
                        size="sm"
                      />
                    }
                    name="Triton"
                  >
                    <ChatMessageBubble variant="ghost" width="100%">
                      <Spinner size="sm" shade="subtle" aria-label="Triton réfléchit" />
                    </ChatMessageBubble>
                  </ChatMessage>
                )}

                {pendingConfirmation && (
                  <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-lg border border-warning bg-warning-muted px-4 py-3">
                    <Text weight="medium" className="text-center">
                      autoriser {pendingConfirmation.tool}(
                      {formatArgs(pendingConfirmation.args)}) ?
                    </Text>
                    <div className="flex flex-wrap justify-center gap-2">
                      <Button
                        label="autoriser"
                        variant="primary"
                        size="sm"
                        onClick={() => {
                          void respondToConfirmation(true);
                        }}
                      >
                        autoriser
                      </Button>
                      <Button
                        label="toujours autoriser pour cette conversation"
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          void respondToConfirmation(true, true);
                        }}
                      >
                        toujours autoriser (cette conversation)
                      </Button>
                      <Button
                        label="refuser"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          void respondToConfirmation(false);
                        }}
                      >
                        refuser
                      </Button>
                    </div>
                  </div>
                )}
              </ChatMessageList>
            </ChatLayout>
            {activeProject ? (
              <ProjectFilePanel
                projectId={activeProject.id}
                projectName={activeProject.name}
                folderPath={activeProject.folder_path}
                refreshSignal={fileRefreshTick}
                tasks={backgroundTasks}
                onOpenTask={openTask}
                onStopTask={stopTask}
                onDeleteTask={deleteTask}
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

      <AlertDialog
        isOpen={deletingProject !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingProject(null);
        }}
        title="Supprimer le projet ?"
        description={`« ${deletingProject?.name ?? ""} » sera supprimé. Ses conversations ne seront pas effacées, mais ne seront plus rattachées au dossier.`}
        actionLabel="Supprimer"
        onAction={confirmDeleteProject}
      />
    </Theme>
  );
}

export default App;
