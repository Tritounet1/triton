import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { open as openFolderDialog } from "@tauri-apps/plugin-dialog";
import { Theme } from "@astryxdesign/core/theme";
import { neutralTheme } from "@astryxdesign/theme-neutral/built";
import { AppShell } from "@astryxdesign/core/AppShell";
import { SideNav, SideNavSection, SideNavItem, SideNavHeading } from "@astryxdesign/core/SideNav";
import { Avatar } from "@astryxdesign/core/Avatar";
import {
  ChatLayout,
  ChatMessageList,
  ChatMessage,
  ChatMessageBubble,
  ChatMessageMetadata,
  ChatToolCalls,
  ChatComposer,
  ChatSystemMessage,
} from "@astryxdesign/core/Chat";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Button } from "@astryxdesign/core/Button";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Markdown } from "@astryxdesign/core/Markdown";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { parseSSE } from "./sse";
import { formatArgs } from "./format";
import { SettingsPage } from "./SettingsPage";
import { ModelPage } from "./ModelPage";
import { LogsPage } from "./LogsPage";
import { McpServersPage } from "./McpServersPage";
import { ProjectFilePanel } from "./ProjectFilePanel";
import { SubagentsPanel } from "./SubagentsPanel";
import {
  CheckIcon,
  ChevronRightIcon,
  CopyIcon,
  FolderIcon,
  GearIcon,
  MoonIcon,
  PencilIcon,
  PlusIcon,
  SearchIcon,
  SunIcon,
  TrashIcon,
} from "./icons";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

// depose le vrai logo Claude a cet emplacement (app-desktop/public/claude-logo.svg) ;
// tant qu'il n'existe pas, Avatar retombe proprement sur les initiales "C".
const CLAUDE_AVATAR_SRC = "/claude-logo.svg";

type ChatMsg =
  | { kind: "user"; text: string; time: number }
  | { kind: "assistant"; text: string; time: number }
  | { kind: "tool"; tool: string; args: Record<string, unknown>; result: string; time: number }
  | { kind: "info"; text: string; time: number }
  | { kind: "error"; text: string; time: number };

interface PendingConfirmation {
  id: string;
  tool: string;
  args: Record<string, unknown>;
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

interface RawSessionMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
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
      out.push({ kind: "user", text: m.content, time: now });
    } else if (m.role === "assistant") {
      for (const toolCall of m.tool_calls ?? []) {
        const args = JSON.parse(toolCall.function.arguments || "{}") as Record<string, unknown>;
        const toolResult = raw.find(
          (x) => x.role === "tool" && x.tool_call_id === toolCall.id,
        );
        out.push({
          kind: "tool",
          tool: toolCall.function.name,
          args,
          result: toolResult?.content ?? "",
          time: now,
        });
      }
      if (m.content) {
        out.push({ kind: "assistant", text: m.content, time: now });
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

type Block = { kind: "tools"; items: ToolMsg[] } | { kind: "text"; msg: AssistantMsg };

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
  return result.startsWith("erreur") || result.startsWith("action refusée")
    ? "error"
    : "complete";
}

function App() {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [apiModel, setApiModel] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
  const [sessions, setSessions] = useState<Session[]>([]);
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editingValue, setEditingValue] = useState("");
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
  const [collapsedProjectIds, setCollapsedProjectIds] = useState<Set<string>>(() => new Set());
  const [fileRefreshTick, setFileRefreshTick] = useState(0);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(
    null,
  );
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
    sendMessageRef.current = (text: string) => { void sendMessage(text); };
  });
  const [themeMode, setThemeMode] = useState<"light" | "dark">(() =>
    localStorage.getItem("triton_theme") === "light" ? "light" : "dark",
  );
  const [view, setView] = useState<"chat" | "settings" | "logs" | "mcp" | "model">("chat");

  function toggleTheme() {
    setThemeMode((prev) => {
      const next = prev === "dark" ? "light" : "dark";
      localStorage.setItem("triton_theme", next);
      return next;
    });
  }

  function loadSessions() {
    fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Session[]) => { setSessions([...list].reverse()); })
      .catch(() => {
        // API hors ligne ou requete echouee : la sidebar reste vide, sans casser l'app
      });
  }

  function loadProjects() {
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((list: Project[]) => { setProjects(list); })
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
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setProjectFormError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      setProjects((await res.json()) as Project[]);
      resetProjectForm();
    } catch {
      setProjectFormError("impossible de contacter l'API Triton (127.0.0.1:8000).");
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

  async function confirmDeleteSession() {
    if (!deletingSession) return;
    setIsDeleting(true);

    try {
      await fetch(`${API_BASE}/sessions/${deletingSession.id}`, { method: "DELETE" });
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
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { ok: boolean; model: string } | null) => { setApiModel(data?.model ?? null); })
      .catch(() => { setApiModel(null); });

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
        .then((data: { id: string; status: string }[]) => {
          const finished = data.find(
            (t) => pendingSubagentIdsRef.current.has(t.id) && t.status !== "running",
          );
          if (!finished) return;
          pendingSubagentIdsRef.current.delete(finished.id);
          sendMessageRef.current(
            `(vérification automatique) Le sous-agent ${finished.id} a terminé, ` +
              "regarde son résultat avec check_subagent et continue la tâche.",
          );
        })
        .catch(() => {
          // API hors ligne : nouvelle tentative au prochain intervalle
        });
    }, 4000);
    return () => { clearInterval(interval); };
  }, []);

  function switchSession(id: string) {
    setView("chat");
    if (id === sessionId || sending) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    setActiveProjectId(sessions.find((s) => s.id === id)?.project_id ?? null);
    pendingSubagentIdsRef.current.clear();
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
  }

  function startProjectSession(projectId: string) {
    setView("chat");
    if (sending) return;
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
    setActiveProjectId(projectId);
    pendingSubagentIdsRef.current.clear();
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

  async function copyToClipboard(text: string, index: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => { setCopiedIndex((current) => (current === index ? null : current)); }, 1500);
  }

  async function sendMessage(rawText: string) {
    const text = rawText.trim();
    if (!text || sending) return;

    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text, time: Date.now() }]);
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
          return [...prev, { kind: "assistant", text: textSoFar, time: Date.now() }];
        });
      });
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text, project_id: activeProjectId }),
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
              const match = /\(id=([a-f0-9]+)\)/.exec((data.result as string) || "");
              if (match?.[1]) pendingSubagentIdsRef.current.add(match[1]);
            }
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
          return [...prev, { kind: "assistant", text: finalText, time: Date.now() }];
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
    return () => { document.removeEventListener("keydown", handleKeyDown); };
  }, [sending, cancelMessage]);

  const filteredSessions = sessions.filter(
    (s) =>
      s.project_id === null &&
      (s.title ?? formatSessionLabel(s.id)).toLowerCase().includes(search.toLowerCase()),
  );

  const activeProject = projects.find((p) => p.id === activeProjectId) ?? null;

  return (
    <Theme theme={neutralTheme} mode={themeMode}>
      <AppShell
        variant="elevated"
        height="fill"
        sideNav={
          <SideNav
            header={<SideNavHeading heading="Triton" />}
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
                    onClick={() => { setSearchOpen((v) => !v); }}
                  />
                </div>
                {searchOpen && (
                  <TextInput
                    value={search}
                    onChange={setSearch}
                    placeholder="Rechercher..."
                    isLabelHidden
                    label="Rechercher une conversation"
                    size="sm"
                    hasAutoFocus
                  />
                )}
              </div>
            }
            footer={
              <div className="flex items-center justify-end gap-0.5 px-1 py-1">
                <IconButton
                  label="Paramètres"
                  icon={<GearIcon />}
                  variant="ghost"
                  size="sm"
                  onClick={() => { setView("settings"); }}
                />
                <IconButton
                  label={themeMode === "dark" ? "Passer en thème clair" : "Passer en thème sombre"}
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
                  onClick={() => { setShowProjectForm((v) => !v); }}
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
                    onClick={() => { void pickProjectFolder(); }}
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
                      onClick={() => { void submitNewProject(); }}
                      className="flex-1"
                    />
                    <Button label="Annuler" variant="ghost" size="sm" onClick={resetProjectForm} />
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
                    <SideNavItem
                      label={p.name}
                      icon={<FolderIcon className="h-4 w-4" />}
                      isSelected={p.id === activeProjectId && sessionId === null}
                      onClick={() => { toggleProjectCollapsed(p.id); }}
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
                    {!isCollapsed &&
                      sessions
                        .filter((s) => s.project_id === p.id)
                        .map((s) => (
                          <SideNavItem
                            key={s.id}
                            label={s.title ?? formatSessionLabel(s.id)}
                            icon={<Avatar name="Claude" src={CLAUDE_AVATAR_SRC} size="xsm" />}
                            isSelected={s.id === sessionId}
                            onClick={() => { switchSession(s.id); }}
                            className="pl-4"
                          />
                        ))}
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
                      onEnter={() => { void commitRename(s.id); }}
                      onBlur={() => { void commitRename(s.id); }}
                      onKeyDown={(e) => {
                        if (e.key === "Escape") setEditingSessionId(null);
                      }}
                    />
                  </div>
                ) : (
                  <SideNavItem
                    key={s.id}
                    label={s.title ?? formatSessionLabel(s.id)}
                    icon={<Avatar name="Claude" src={CLAUDE_AVATAR_SRC} size="xsm" />}
                    isSelected={s.id === sessionId}
                    onClick={() => { switchSession(s.id); }}
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
            onBack={() => { setView("chat"); }}
            onOpenLogs={() => { setView("logs"); }}
            onOpenMcp={() => { setView("mcp"); }}
            onOpenModel={() => { setView("model"); }}
          />
        )}
        {view === "logs" && <LogsPage onBack={() => { setView("settings"); }} />}
        {view === "mcp" && <McpServersPage onBack={() => { setView("settings"); }} />}
        {view === "model" && <ModelPage onBack={() => { setView("settings"); }} />}
        {view === "chat" && (
        <div className="flex h-full">
        <ChatLayout
          density="balanced"
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
              onSubmit={(value) => { void sendMessage(value); }}
              onStop={cancelMessage}
              isStopShown={sending}
              placeholder="Écrire un message..."
              isDisabled={sending || !!pendingConfirmation}
              density="compact"
              elevation="none"
              style={{ "--_chat-composer-padding": "16px" } as CSSProperties}
              footerActions={
                <IconButton
                  label="Joindre (pas encore disponible)"
                  icon={<PlusIcon />}
                  variant="ghost"
                  size="sm"
                  isDisabled
                />
              }
              sendActions={
                apiModel ? (
                  <Text size="2xs" color="secondary">
                    {apiModel}
                  </Text>
                ) : undefined
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
                          timestamp={<Timestamp value={group.msg.time / 1000} format="time" />}
                          status="sent"
                        />
                      }
                    >
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
              if (!lastItem) throw new Error("groupe assistant sans element");
              const lastIsText = lastItem.kind === "assistant";

              return (
                <ChatMessage
                  key={gi}
                  sender="assistant"
                  avatar={<Avatar name="Claude" src={CLAUDE_AVATAR_SRC} size="sm" />}
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
                          resultDetail: (
                            <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap text-xs">
                              {t.result}
                            </pre>
                          ),
                        }))}
                      />
                    ) : (
                      <ChatMessageBubble key={bi} variant="ghost" width="100%">
                        <Markdown>{block.msg.text}</Markdown>
                      </ChatMessageBubble>
                    ),
                  )}
                  <ChatMessageMetadata
                    timestamp={<Timestamp value={lastItem.time / 1000} format="time" />}
                    footer={
                      lastIsText && lastItem.text ? (
                        <button
                          onClick={() => { void copyToClipboard(lastItem.text, gi); }}
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

            {pendingConfirmation && (
              <div className="mx-auto flex max-w-md flex-col items-center gap-3 rounded-lg border border-warning bg-warning-muted px-4 py-3">
                <Text weight="medium" className="text-center">
                  autoriser {pendingConfirmation.tool}({formatArgs(pendingConfirmation.args)}) ?
                </Text>
                <div className="flex flex-wrap justify-center gap-2">
                  <Button
                    label="autoriser"
                    variant="primary"
                    size="sm"
                    onClick={() => { void respondToConfirmation(true); }}
                  >
                    autoriser
                  </Button>
                  <Button
                    label="toujours autoriser pour cette conversation"
                    variant="secondary"
                    size="sm"
                    onClick={() => { void respondToConfirmation(true, true); }}
                  >
                    toujours autoriser (cette conversation)
                  </Button>
                  <Button
                    label="refuser"
                    variant="ghost"
                    size="sm"
                    onClick={() => { void respondToConfirmation(false); }}
                  >
                    refuser
                  </Button>
                </div>
              </div>
            )}
          </ChatMessageList>
        </ChatLayout>
        {activeProject && (
          <ProjectFilePanel
            projectId={activeProject.id}
            projectName={activeProject.name}
            folderPath={activeProject.folder_path}
            refreshSignal={fileRefreshTick}
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
