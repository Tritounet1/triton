import { useEffect, useState, type CSSProperties } from "react";
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
import { LogsPage } from "./LogsPage";
import { McpServersPage } from "./McpServersPage";
import {
  CheckIcon,
  CopyIcon,
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
}

interface RawSessionMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" */
function formatSessionLabel(id: string): string {
  const m = id.match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (!m) return id;
  const [, y, mo, d, h, mi] = m;
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(
    null,
  );
  const [themeMode, setThemeMode] = useState<"light" | "dark">(() =>
    localStorage.getItem("triton_theme") === "light" ? "light" : "dark",
  );
  const [view, setView] = useState<"chat" | "settings" | "logs" | "mcp">("chat");

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
      .then((list: Session[]) => setSessions([...list].reverse()))
      .catch(() => {});
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
      .catch(() => {});
  }

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { ok: boolean; model: string } | null) => setApiModel(data?.model ?? null))
      .catch(() => setApiModel(null));

    loadSessions();

    // uniquement au demarrage, pour une session deja connue (localStorage) ;
    // ne doit pas se redeclencher quand sendMessage() fixe sessionId lui-meme,
    // sinon ca part en course avec le streaming en cours.
    const stored = localStorage.getItem("triton_session_id");
    if (stored) loadHistory(stored);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function switchSession(id: string) {
    setView("chat");
    if (id === sessionId || sending) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    loadHistory(id);
  }

  function startNewSession() {
    setView("chat");
    if (sending) return;
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
  }

  async function copyToClipboard(text: string, index: number) {
    await navigator.clipboard.writeText(text);
    setCopiedIndex(index);
    setTimeout(() => setCopiedIndex((current) => (current === index ? null : current)), 1500);
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
          if (last && last.kind === "assistant") {
            return [...prev.slice(0, -1), { ...last, text: textSoFar }];
          }
          return [...prev, { kind: "assistant", text: textSoFar, time: Date.now() }];
        });
      });
    }

    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: text }),
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
            setSessions((prev) =>
              prev.some((s) => s.id === currentSessionId)
                ? prev.map((s) => (s.id === currentSessionId ? { ...s, title } : s))
                : [{ id: currentSessionId!, title }, ...prev],
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
      console.error("erreur pendant l'échange avec l'API Triton :", err);
      setMessages((prev) => [
        ...prev,
        {
          kind: "error",
          text: "impossible de contacter l'API Triton (127.0.0.1:8000).",
          time: Date.now(),
        },
      ]);
    } finally {
      setSending(false);
      loadSessions();
    }
  }

  async function respondToConfirmation(approved: boolean, remember = false) {
    if (!pendingConfirmation) return;
    const { id } = pendingConfirmation;
    setPendingConfirmation(null);

    await fetch(`${API_BASE}/chat/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: id, approved, remember }),
    });
  }

  const filteredSessions = sessions.filter((s) =>
    (s.title ?? formatSessionLabel(s.id)).toLowerCase().includes(search.toLowerCase()),
  );

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
                    onClick={() => setSearchOpen((v) => !v)}
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
                  onClick={() => setView("settings")}
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
                      onEnter={() => commitRename(s.id)}
                      onBlur={() => commitRename(s.id)}
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
                    onClick={() => switchSession(s.id)}
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
            onBack={() => setView("chat")}
            onOpenLogs={() => setView("logs")}
            onOpenMcp={() => setView("mcp")}
          />
        )}
        {view === "logs" && <LogsPage onBack={() => setView("settings")} />}
        {view === "mcp" && <McpServersPage onBack={() => setView("settings")} />}
        {view === "chat" && (
        <ChatLayout
          density="balanced"
          className="h-full"
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
              onSubmit={sendMessage}
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
                          onClick={() => copyToClipboard(lastItem.text, gi)}
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
                    onClick={() => respondToConfirmation(true)}
                  >
                    autoriser
                  </Button>
                  <Button
                    label="toujours autoriser pour cette conversation"
                    variant="secondary"
                    size="sm"
                    onClick={() => respondToConfirmation(true, true)}
                  >
                    toujours autoriser (cette conversation)
                  </Button>
                  <Button
                    label="refuser"
                    variant="ghost"
                    size="sm"
                    onClick={() => respondToConfirmation(false)}
                  >
                    refuser
                  </Button>
                </div>
              </div>
            )}
          </ChatMessageList>
        </ChatLayout>
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
    </Theme>
  );
}

export default App;
