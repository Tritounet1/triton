import type { Dispatch, SetStateAction } from "react";
import {
  isPdfDataUrl,
  type ChatMsg,
  type MultiAgentSubtaskToolCall,
} from "./chatMessages";
import {
  fetchSnapshotDiff,
  fetchSnapshotPoints,
  type SnapshotDiff,
  type SnapshotPoint,
} from "./snapshotDiff";
import { moveInFlightModel, setInFlightModel } from "./inFlightModels";
import { API_BASE } from "./api";


export const MULTI_AGENT_PREFIX = "/multi-agents ";
const MULTI_AGENT_POLL_INTERVAL_MS = 1500;
export const MODEL_COMMAND_PREFIX = "/model ";
export const COST_COMMAND = "/cost";
export const UNDO_COMMAND = "/undo";
export const REMEMBER_PREFIX = "/remember ";
const REMEMBER_SESSION_PREFIX = "session ";
const REMEMBER_GLOBAL_PREFIX = "global ";
export const COMPACT_COMMAND = "/compact";
export const YOLO_COMMAND = "/yolo";

interface MultiAgentSubtask {
  id: string;
  role: string;
  description: string;
  model: string;
  status: "pending" | "running" | "done" | "error";
  result: string | null;
  tool_calls: MultiAgentSubtaskToolCall[];
}

interface MultiAgentRun {
  id: string;
  task: string;
  status: "planning" | "running" | "done" | "error";
  subtasks: MultiAgentSubtask[];
  final_result: string | null;
  error: string | null;
}

export interface PendingAttachment {
  name: string;
  dataUrl: string;
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
}

interface ModelCatalogEntry {
  id: string;
  name: string;
}

export interface ChatCommandsDeps {
  sessionId: string | null;
  activeProjectId: string | null;
  activeProject: Project | null;
  modelsCatalog: ModelCatalogEntry[];
  undoTarget: SnapshotPoint | null;
  sending: boolean;
  pendingAttachments: PendingAttachment[];
  pendingTextAttachments: { name: string; content: string }[];
  oneShotImageModel: string | null;
  imageModel: string | null;
  getDisplayedSessionId: () => string | null;
  setDisplayedSessionId: (id: string) => void;
  getAbortControllers: () => Map<string, AbortController>;
  setInput: (value: string) => void;
  setMessages: Dispatch<SetStateAction<ChatMsg[]>>;
  setSessions: Dispatch<SetStateAction<Session[]>>;
  setSessionId: Dispatch<SetStateAction<string | null>>;
  setSessionModelOverride: (id: string) => void;
  setUndoDiff: (diff: SnapshotDiff | null) => void;
  setUndoTarget: (point: SnapshotPoint | null) => void;
  setUndoing: (value: boolean) => void;
  setFileRefreshTick: Dispatch<SetStateAction<number>>;
  setYoloEnabled: (value: boolean) => void;
  setSendingSessionIds: Dispatch<SetStateAction<Set<string>>>;
  setInFlightModels: Dispatch<SetStateAction<Record<string, string>>>;
  setOneShotImageModel: (value: string | null) => void;
  setPendingAttachments: Dispatch<SetStateAction<PendingAttachment[]>>;
  setImageMode: (value: boolean) => void;
  setPreviewImage: (value: string | null) => void;
  loadSessions: () => Promise<Session[]>;
}

export interface ChatCommands {
  markSending: (key: string, isSending: boolean) => void;
  markInFlightModel: (key: string, model: string | null) => void;
  moveSendingKey: (oldKey: string, newKey: string) => void;
  dispatchMultiAgent: (rawCommand: string) => Promise<void>;
  handleCostCommand: () => Promise<void>;
  handleModelCommand: (rawCommand: string) => Promise<void>;
  handleUndoCommand: () => Promise<void>;
  confirmUndo: () => Promise<void>;
  handleRememberCommand: (rawCommand: string) => Promise<void>;
  handleCompactCommand: () => Promise<void>;
  handleYoloCommand: () => Promise<void>;
  requestImageChange: (src: string) => void;
  generateImage: (rawPrompt: string) => Promise<void>;
}

export function createChatCommands(deps: ChatCommandsDeps): ChatCommands {
  const {
    getDisplayedSessionId,
    setDisplayedSessionId,
    getAbortControllers,
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
  } = deps;

  function markSending(key: string, isSending: boolean) {
    setSendingSessionIds((prev) => {
      if (isSending === prev.has(key)) return prev;
      const next = new Set(prev);
      if (isSending) next.add(key);
      else next.delete(key);
      return next;
    });
  }

  function markInFlightModel(key: string, model: string | null) {
    setInFlightModels((previous) => setInFlightModel(previous, key, model));
  }

  // Moves a sendingSessionIds entry from one key to another in a single
  // state update (not a separate delete + add) - a brand-new conversation
  // moves from the "" key to its real id as soon as the server announces it
  // ("session" event), and doing it in two steps would risk an intermediate
  // render where neither key is present (composer would flicker "not
  // sending").
  function moveSendingKey(oldKey: string, newKey: string) {
    setSendingSessionIds((prev) => {
      if (!prev.has(oldKey)) return prev;
      const next = new Set(prev);
      next.delete(oldKey);
      next.add(newKey);
      return next;
    });
    setInFlightModels((previous) => moveInFlightModel(previous, oldKey, newKey));
  }

  // Polls a multi-agent run until it finishes, updating (not stacking) one
  // "tool" entry per subtask as it goes: same rendering as real tool calls
  // (ChatToolCalls), just with a directly known status rather than one
  // inferred from text (see ChatMsg). `targetSessionId`: the conversation
  // this run belongs to, to filter `messages` updates against the
  // displayed one - same principle as isDisplayed() in sendMessage, needed
  // here too since switching conversations mid-send is allowed (a
  // multi-agent run started in a conversation you've left must not write
  // into the one you're now viewing).
  function pollMultiAgentRun(runId: string, targetSessionId: string | null): Promise<void> {
    function isDisplayed(): boolean {
      return getDisplayedSessionId() === targetSessionId;
    }
    return new Promise((resolve) => {
      const interval = setInterval(() => {
        fetch(`${API_BASE}/orchestrator/${runId}`)
          .then((r) => (r.ok ? r.json() : null))
          .then((run: MultiAgentRun | null) => {
            if (!run) return;

            if (run.subtasks.length > 0 && isDisplayed()) {
              setMessages((prev) => {
                const next = [...prev];
                for (const s of run.subtasks) {
                  const entry: ChatMsg = {
                    kind: "tool",
                    id: s.id,
                    tool: s.role,
                    args: { model: s.model },
                    result: s.result ?? "",
                    time: Date.now(),
                    status: s.status === "done" ? "complete" : s.status,
                    subtaskDescription: s.description,
                    subtaskToolCalls: s.tool_calls,
                  };
                  const idx = next.findIndex((m) => m.kind === "tool" && m.id === s.id);
                  if (idx >= 0) next[idx] = entry;
                  else next.push(entry);
                }
                return next;
              });
            }

            if (run.status === "done" || run.status === "error") {
              clearInterval(interval);
              if (isDisplayed()) {
                const finalText =
                  run.status === "done"
                    ? (run.final_result ?? "(le planificateur n'a rien synthétisé)")
                    : (run.error ?? "le run multi-agent a échoué");
                setMessages((prev) => [
                  ...prev,
                  { kind: "assistant", text: finalText, time: Date.now() },
                ]);
              }
              resolve();
            }
          })
          .catch(() => {
            // offline: retried on the next interval
          });
      }, MULTI_AGENT_POLL_INTERVAL_MS);
    });
  }

  async function dispatchMultiAgent(rawCommand: string) {
    const task = rawCommand.slice(MULTI_AGENT_PREFIX.length).trim();
    if (!task) return;

    const startSessionId = deps.sessionId;
    const sessionKey = startSessionId ?? "";
    let currentSessionId = startSessionId;
    function isDisplayed(): boolean {
      return getDisplayedSessionId() === currentSessionId;
    }

    setInput("");
    if (isDisplayed()) {
      setMessages((prev) => [...prev, { kind: "user", text: rawCommand, time: Date.now() }]);
    }
    markSending(sessionKey, true);

    try {
      const res = await fetch(`${API_BASE}/orchestrator`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task,
          session_id: startSessionId,
          project_id: deps.activeProjectId,
        }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as { run_id: string; session_id: string };

      if (data.session_id !== startSessionId) {
        moveSendingKey(sessionKey, data.session_id);
        currentSessionId = data.session_id;
        if (getDisplayedSessionId() === startSessionId) {
          setSessionId(data.session_id);
          localStorage.setItem("triton_session_id", data.session_id);
          setDisplayedSessionId(data.session_id);
        }
      }
      void loadSessions();

      await pollMultiAgentRun(data.run_id, currentSessionId);
    } catch {
      if (isDisplayed()) {
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
      markSending(currentSessionId ?? sessionKey, false);
      void loadSessions();
    }
  }

  /** /cost: quick cost/token summary of the current conversation, purely
   * local - no round-trip through the model, just a GET on the endpoint
   * that timed_stream_chat feeds on every turn (see chat_loop.py). */
  async function handleCostCommand() {
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: COST_COMMAND, time: Date.now() }]);

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "Aucune conversation active pour l'instant - envoie d'abord un message.",
          time: Date.now(),
        },
      ]);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/sessions/${deps.sessionId}/cost`);
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as {
        calls: number;
        prompt_tokens: number;
        completion_tokens: number;
        total_tokens: number;
        cost_usd: number;
      };
      const fmt = (n: number) => n.toLocaleString("fr-FR");
      setMessages((prev) => [
        ...prev,
        {
          kind: "info",
          text:
            `${data.calls} appel(s) modèle · ${fmt(data.total_tokens)} tokens ` +
            `(${fmt(data.prompt_tokens)} entrée / ${fmt(data.completion_tokens)} sortie) · ` +
            `~$${data.cost_usd.toFixed(4)}`,
          time: Date.now(),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "impossible de récupérer le coût de cette conversation.",
          time: Date.now(),
        },
      ]);
    }
  }

  /** /model <query>: looks in the already-loaded OpenRouter catalog
   * (modelsCatalog) for a model whose id or name contains the query, and
   * makes it THIS conversation's override (PUT /sessions/{id}/model) - no
   * need to type the exact id ("gpt-5" is enough to find "openai/gpt-5"). */
  async function handleModelCommand(rawCommand: string) {
    const query = rawCommand.slice(MODEL_COMMAND_PREFIX.length).trim();
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: rawCommand, time: Date.now() }]);

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "Aucune conversation active pour l'instant - envoie d'abord un message.",
          time: Date.now(),
        },
      ]);
      return;
    }
    if (!query) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "Précise un modèle, ex. /model gpt-5", time: Date.now() },
      ]);
      return;
    }

    const q = query.toLowerCase();
    const matches = deps.modelsCatalog.filter(
      (m) => m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q),
    );
    if (matches.length === 0) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: `Aucun modèle ne correspond à « ${query} ».`, time: Date.now() },
      ]);
      return;
    }

    const chosen = matches[0];
    if (!chosen) return;
    await fetch(`${API_BASE}/sessions/${deps.sessionId}/model`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: chosen.id }),
    });
    setSessionModelOverride(chosen.id);
    const note =
      matches.length > 1
        ? ` (${matches.length} correspondances, la plus proche a été prise)`
        : "";
    setMessages((prev) => [
      ...prev,
      {
        kind: "info",
        text: `Modèle de cette conversation changé pour ${chosen.name}${note}.`,
        time: Date.now(),
      },
    ]);
  }

  /** /undo: triggers the safety-net restore (see SnapshotSection.tsx for the
   * same mechanism via the files panel) - first checks a snapshot exists so
   * it doesn't open a confirmation for nothing, then asks for confirmation
   * before restoring (irreversible, even from a command). */
  async function handleUndoCommand() {
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: UNDO_COMMAND, time: Date.now() }]);

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "Aucune conversation active pour l'instant.", time: Date.now() },
      ]);
      return;
    }

    let points: SnapshotPoint[];
    try {
      points = await fetchSnapshotPoints(deps.sessionId);
    } catch {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "Impossible de charger les points de restauration.",
          time: Date.now(),
        },
      ]);
      return;
    }
    if (points.length === 0) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "info",
          text: "Aucun filet de sécurité pour cette conversation : aucune écriture n'a encore eu lieu.",
          time: Date.now(),
        },
      ]);
      return;
    }
    const target = points[points.length - 1];
    // guaranteed defined by points.length === 0 already returning above -
    // narrows for TS's noUncheckedIndexedAccess without a non-null
    // assertion (forbidden by this project's eslint config)
    if (!target) return;
    setUndoDiff(null);
    setUndoTarget(target);
    void fetchSnapshotDiff(deps.sessionId, target.turn_index, "rollback")
      .then(setUndoDiff)
      .catch(() => {
        setUndoDiff(null);
      });
  }

  async function confirmUndo() {
    if (!deps.sessionId || !deps.undoTarget) return;
    setUndoing(true);
    try {
      const res = await fetch(`${API_BASE}/sessions/${deps.sessionId}/snapshot/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn_index: deps.undoTarget.turn_index, state: "before" }),
      });
      setMessages((prev) => [
        ...prev,
        res.ok
          ? {
              kind: "info",
              text: "Filet de sécurité restauré : le dossier du projet est revenu à l'état d'avant le dernier message.",
              time: Date.now(),
            }
          : { kind: "error", text: "La restauration a échoué.", time: Date.now() },
      ]);
      setFileRefreshTick((t) => t + 1);
    } finally {
      setUndoing(false);
      setUndoTarget(null);
    }
  }

  /** /remember session <note> or /remember global <note>: calls the
   * remember tool (or the global-memory equivalent) directly, bypassing the
   * model - a shortcut to jot something down fast. The "session" scope
   * follows the exact same logic as the tool (POST /sessions/{id}/remember
   * reuses it server-side): the project's memory if the conversation has
   * one, otherwise the conversation's own - never both. */
  async function handleRememberCommand(rawCommand: string) {
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: rawCommand, time: Date.now() }]);

    const rest = rawCommand.slice(REMEMBER_PREFIX.length);
    const restLower = rest.toLowerCase();
    const isGlobal = restLower.startsWith(REMEMBER_GLOBAL_PREFIX);
    const isSession = restLower.startsWith(REMEMBER_SESSION_PREFIX);
    const note = isGlobal
      ? rest.slice(REMEMBER_GLOBAL_PREFIX.length).trim()
      : isSession
        ? rest.slice(REMEMBER_SESSION_PREFIX.length).trim()
        : "";

    if (!isGlobal && !isSession) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "Précise la portée : /remember session <note> ou /remember global <note>",
          time: Date.now(),
        },
      ]);
      return;
    }
    if (!note) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "Précise une note à retenir.", time: Date.now() },
      ]);
      return;
    }

    if (isGlobal) {
      try {
        const res = await fetch(`${API_BASE}/memory/global`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ note }),
        });
        if (!res.ok) throw new Error(String(res.status));
        setMessages((prev) => [
          ...prev,
          { kind: "info", text: `Retenu dans la mémoire globale : ${note}`, time: Date.now() },
        ]);
      } catch {
        setMessages((prev) => [
          ...prev,
          { kind: "error", text: "impossible d'enregistrer cette note.", time: Date.now() },
        ]);
      }
      return;
    }

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "Aucune conversation active pour l'instant - envoie d'abord un message.",
          time: Date.now(),
        },
      ]);
      return;
    }
    try {
      const res = await fetch(`${API_BASE}/sessions/${deps.sessionId}/remember`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note }),
      });
      if (!res.ok) throw new Error(String(res.status));
      const scopeLabel = deps.activeProject
        ? `le projet « ${deps.activeProject.name} »`
        : "cette conversation";
      setMessages((prev) => [
        ...prev,
        { kind: "info", text: `Retenu pour ${scopeLabel} : ${note}`, time: Date.now() },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "impossible d'enregistrer cette note.", time: Date.now() },
      ]);
    }
  }

  /** /compact: forces summarizing the oldest exchanges right now (POST
   * /sessions/{id}/compact, reuses compress_history_if_needed with
   * force=True server-side), rather than waiting for the automatic trigger
   * when context exceeds MAX_CONTEXT_CHARS (see chat_loop.py). */
  async function handleCompactCommand() {
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: COMPACT_COMMAND, time: Date.now() }]);

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "Aucune conversation active pour l'instant.", time: Date.now() },
      ]);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/sessions/${deps.sessionId}/compact`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as { result: string };
      setMessages((prev) => [...prev, { kind: "info", text: data.result, time: Date.now() }]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "impossible de résumer cette conversation.", time: Date.now() },
      ]);
    }
  }

  /** /yolo: toggles YOLO mode for this conversation (POST /sessions/{id}/yolo,
   * a plain server-side toggle - running the command again turns it off) -
   * while active, run_chat_stream skips the confirmation prompt for any
   * non-read-only tool (see the persistent banner shown near the composer
   * below, not just this one-off message). */
  async function handleYoloCommand() {
    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text: YOLO_COMMAND, time: Date.now() }]);

    if (!deps.sessionId) {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "Aucune conversation active pour l'instant.", time: Date.now() },
      ]);
      return;
    }

    try {
      const res = await fetch(`${API_BASE}/sessions/${deps.sessionId}/yolo`, {
        method: "POST",
      });
      if (!res.ok) throw new Error(String(res.status));
      const data = (await res.json()) as { enabled: boolean };
      setYoloEnabled(data.enabled);
      setMessages((prev) => [
        ...prev,
        {
          kind: "info",
          text: data.enabled
            ? "Mode YOLO activé pour cette conversation : les demandes d'autorisation sont sautées pour toute action (écriture, commande...). Retape /yolo pour désactiver."
            : "Mode YOLO désactivé - les demandes d'autorisation sont de retour.",
          time: Date.now(),
        },
      ]);
    } catch {
      setMessages((prev) => [
        ...prev,
        { kind: "error", text: "impossible de changer le mode YOLO.", time: Date.now() },
      ]);
    }
  }

  function requestImageChange(src: string) {
    setPendingAttachments((previous) =>
      previous.some((attachment) => attachment.dataUrl === src)
        ? previous
        : [...previous, { name: "image-de-reference.png", dataUrl: src }],
    );
    setImageMode(true);
    setPreviewImage(null);
  }

  async function generateImage(rawPrompt: string) {
    const prompt = rawPrompt.trim();
    if (!prompt || deps.sending) {
      if (deps.sending) setInput(rawPrompt);
      return;
    }
    if (
      deps.pendingTextAttachments.length ||
      deps.pendingAttachments.some((attachment) => isPdfDataUrl(attachment.dataUrl))
    ) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "La génération d’images accepte des images de référence, pas des PDF ou des fichiers texte.",
          time: Date.now(),
        },
      ]);
      setInput(rawPrompt);
      return;
    }

    // The temporary choice is consumed now. It is sent to this request but
    // never written into settings.json, and the next image starts from the
    // default selected in Settings again.
    const requestModel = deps.oneShotImageModel;
    const inFlightModel = requestModel ?? deps.imageModel;
    const references = deps.pendingAttachments;
    setOneShotImageModel(null);
    setInput("");
    setPendingAttachments([]);

    const startSessionId = deps.sessionId;
    let currentSessionId = startSessionId;
    let currentSessionKey = startSessionId ?? "";
    const isDisplayed = () => getDisplayedSessionId() === currentSessionId;

    if (isDisplayed()) {
      setMessages((prev) => [
        ...prev,
        {
          kind: "user",
          text: prompt,
          images: references.map((attachment) => attachment.dataUrl),
          time: Date.now(),
        },
      ]);
    }
    markSending(currentSessionKey, true);
    markInFlightModel(currentSessionKey, inFlightModel);
    const controller = new AbortController();
    getAbortControllers().set(currentSessionKey, controller);

    try {
      const response = await fetch(`${API_BASE}/images/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: startSessionId,
          prompt,
          project_id: deps.activeProjectId,
          model: requestModel,
          attachments: references.map((attachment) => ({
            name: attachment.name,
            data_url: attachment.dataUrl,
          })),
        }),
        signal: controller.signal,
      });
      const payload = (await response.json()) as {
        session_id?: string;
        title?: string | null;
        model?: string;
        images?: string[];
        detail?: string;
      };
      if (!response.ok) throw new Error(payload.detail ?? `Erreur ${response.status}`);

      const newId = payload.session_id;
      if (!newId) throw new Error("L’API n’a pas retourné de conversation.");
      const wasNew = currentSessionId === null;
      currentSessionId = newId;
      if (wasNew) {
        moveSendingKey(currentSessionKey, newId);
        const controllerForThis = getAbortControllers().get(currentSessionKey);
        getAbortControllers().delete(currentSessionKey);
        currentSessionKey = newId;
        if (controllerForThis) getAbortControllers().set(newId, controllerForThis);
        if (getDisplayedSessionId() === startSessionId) {
          setSessionId(newId);
          localStorage.setItem("triton_session_id", newId);
          setDisplayedSessionId(newId);
        }
      }

      const title = payload.title;
      if (title) {
        setSessions((prev) =>
          prev.some((item) => item.id === newId)
            ? prev.map((item) => (item.id === newId ? { ...item, title } : item))
            : [{ id: newId, title, project_id: deps.activeProjectId, pinned: false }, ...prev],
        );
      }
      if (isDisplayed()) {
        setMessages((prev) => [
          ...prev,
          {
            kind: "assistant",
            text: "",
            images: payload.images ?? [],
            model: payload.model,
            time: Date.now(),
          },
        ]);
      }
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError") && isDisplayed()) {
        setMessages((prev) => [
          ...prev,
          {
            kind: "error",
            text: error instanceof Error ? error.message : "Impossible de générer l’image.",
            time: Date.now(),
          },
        ]);
      }
    } finally {
      getAbortControllers().delete(currentSessionKey);
      markSending(currentSessionKey, false);
      markInFlightModel(currentSessionKey, null);
      void loadSessions();
    }
  }

  return {
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
  };
}
