import { useEffect, useRef, useState } from "react";
import { parseSSE } from "./sse";
import { ArrowUpIcon, CheckIcon, CopyIcon, PlusIcon, SearchIcon } from "./icons";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

type ChatMessage =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string }
  | { kind: "tool"; tool: string; args: Record<string, unknown>; result: string }
  | { kind: "info"; text: string }
  | { kind: "error"; text: string };

interface PendingConfirmation {
  id: string;
  tool: string;
  args: Record<string, unknown>;
}

interface RawSessionMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | null;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
}

function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => {
      if (k === "content" && typeof v === "string") {
        return `${k}=<${v.length} caractères>`;
      }
      return `${k}=${JSON.stringify(v)}`;
    })
    .join(", ");
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" */
function formatSessionLabel(id: string): string {
  const m = id.match(/^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/);
  if (!m) return id;
  const [, y, mo, d, h, mi] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

function historyToMessages(raw: RawSessionMessage[]): ChatMessage[] {
  const out: ChatMessage[] = [];

  for (const m of raw) {
    if (m.role === "user" && m.content) {
      out.push({ kind: "user", text: m.content });
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
        });
      }
      if (m.content) {
        out.push({ kind: "assistant", text: m.content });
      }
    }
  }

  return out;
}

function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [apiModel, setApiModel] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
  const [sessions, setSessions] = useState<string[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(
    null,
  );

  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  function loadSessions() {
    fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((ids: string[]) => setSessions([...ids].reverse()))
      .catch(() => {});
  }

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { ok: boolean; model: string } | null) => {
        setApiOnline(!!data?.ok);
        setApiModel(data?.model ?? null);
      })
      .catch(() => setApiOnline(false));

    loadSessions();

    // uniquement au démarrage, pour une session déjà connue (localStorage).
    // ne doit pas se redéclencher quand sendMessage() fixe sessionId lui-même
    // via l'événement "session", sinon ça part en course avec le streaming
    // en cours (fetch concurrent + setMessages qui écrase l'état en cours).
    const stored = localStorage.getItem("triton_session_id");
    if (stored) loadHistory(stored);
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [input]);

  function loadHistory(id: string) {
    fetch(`${API_BASE}/sessions/${id}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((raw: RawSessionMessage[] | null) => {
        if (raw) setMessages(historyToMessages(raw));
      })
      .catch(() => {});
  }

  function switchSession(id: string) {
    if (id === sessionId || sending) return;
    setSessionId(id);
    localStorage.setItem("triton_session_id", id);
    setMessages([]);
    loadHistory(id);
  }

  function startNewSession() {
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

  async function sendMessage() {
    const text = input.trim();
    if (!text || sending) return;

    setInput("");
    setMessages((prev) => [...prev, { kind: "user", text }]);
    setSending(true);

    let assistantText = "";
    let flushScheduled = false;

    // les tokens peuvent arriver bien plus vite que le rythme d'affichage
    // utile (le webview a du mal à suivre un setMessages() par token) : on
    // regroupe les mises à jour par frame plutôt que d'en déclencher une à
    // chaque morceau de texte reçu. L'updater ne doit dépendre que de `prev`
    // (pas d'un index externe muté à l'intérieur), sinon React (StrictMode
    // rejoue les updaters pour vérifier qu'ils sont purs) plante au second
    // passage avec un index déjà décalé.
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
          return [...prev, { kind: "assistant", text: textSoFar }];
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
            if (id !== sessionId) {
              setSessionId(id);
              localStorage.setItem("triton_session_id", id);
            }
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
            setMessages((prev) => [...prev, { kind: "info", text: data.message as string }]);
            break;
          }
          case "error": {
            setMessages((prev) => [...prev, { kind: "error", text: data.message as string }]);
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
        { kind: "error", text: "impossible de contacter l'API Triton (127.0.0.1:8000)." },
      ]);
    } finally {
      setSending(false);
      loadSessions();
    }
  }

  async function respondToConfirmation(approved: boolean) {
    if (!pendingConfirmation) return;
    const { id } = pendingConfirmation;
    setPendingConfirmation(null);

    await fetch(`${API_BASE}/chat/confirm`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_id: id, approved }),
    });
  }

  const filteredSessions = sessions.filter((id) =>
    formatSessionLabel(id).toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="flex h-screen text-sm text-ink bg-void">
      <aside className="flex w-64 flex-shrink-0 flex-col border-r border-border bg-sidebar">
        <div className="flex items-center justify-between px-4 py-4">
          <span className="font-bold tracking-wide text-accent">Triton</span>
          <button
            onClick={() => setSearchOpen((v) => !v)}
            className="rounded-lg p-1.5 text-ink-dim hover:bg-panel hover:text-ink"
            title="Rechercher"
          >
            <SearchIcon />
          </button>
        </div>

        {searchOpen && (
          <div className="px-3 pb-2">
            <input
              autoFocus
              value={search}
              onChange={(e) => setSearch(e.currentTarget.value)}
              placeholder="Rechercher..."
              className="w-full rounded-lg border border-border bg-panel px-3 py-1.5 text-xs outline-none focus:border-accent"
            />
          </div>
        )}

        <div className="px-2">
          <button
            onClick={startNewSession}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-ink-dim hover:bg-panel hover:text-ink"
          >
            <PlusIcon />
            Nouvelle conversation
          </button>
        </div>

        <div className="px-4 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-ink-dim">
          Conversations
        </div>

        <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
          {filteredSessions.length === 0 && (
            <p className="px-3 py-2 text-xs text-ink-dim">Aucune conversation.</p>
          )}
          {filteredSessions.map((id) => (
            <button
              key={id}
              onClick={() => switchSession(id)}
              className={`block w-full truncate rounded-lg px-3 py-2 text-left text-sm ${
                id === sessionId
                  ? "bg-panel text-ink"
                  : "text-ink-dim hover:bg-panel/60 hover:text-ink"
              }`}
            >
              {formatSessionLabel(id)}
            </button>
          ))}
        </div>

        <div className="flex items-center justify-between border-t border-border px-4 py-3 text-xs text-ink-dim">
          <span>Triton · local</span>
          <span className={apiOnline ? "text-ok" : "text-danger"}>
            {apiOnline === null ? "…" : apiOnline ? "● en ligne" : "● hors ligne"}
          </span>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 flex-shrink-0 items-center border-b border-border px-6">
          <h1 className="truncate font-semibold">
            {sessionId ? formatSessionLabel(sessionId) : "Nouvelle conversation"}
          </h1>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
            {messages.length === 0 && (
              <p className="mt-20 text-center text-ink-dim">
                Écris un message pour démarrer la conversation.
              </p>
            )}

            {messages.map((m, i) => {
              if (m.kind === "user") {
                return (
                  <div key={i} className="flex justify-end">
                    <div className="max-w-[75%] whitespace-pre-wrap rounded-2xl border border-accent-dim/50 bg-accent-dim/30 px-4 py-2.5">
                      {m.text}
                    </div>
                  </div>
                );
              }
              if (m.kind === "assistant") {
                return (
                  <div key={i}>
                    <div className="whitespace-pre-wrap leading-relaxed">{m.text}</div>
                    {m.text && (
                      <div className="mt-2 flex items-center gap-3 text-ink-dim">
                        <button
                          onClick={() => copyToClipboard(m.text, i)}
                          className="hover:text-ink"
                          title="Copier"
                        >
                          {copiedIndex === i ? (
                            <CheckIcon className="h-3.5 w-3.5 text-ok" />
                          ) : (
                            <CopyIcon className="h-3.5 w-3.5" />
                          )}
                        </button>
                      </div>
                    )}
                  </div>
                );
              }
              if (m.kind === "tool") {
                return (
                  <div key={i} className="rounded-xl border border-warn/40 bg-warn/5 px-4 py-3 text-xs">
                    <div className="mb-1 font-medium text-warn">
                      outil : {m.tool}({formatArgs(m.args)})
                    </div>
                    <div className="max-h-48 overflow-y-auto whitespace-pre-wrap text-ink-dim">
                      {m.result}
                    </div>
                  </div>
                );
              }
              if (m.kind === "info") {
                return (
                  <p key={i} className="text-xs italic text-ink-dim">
                    {m.text}
                  </p>
                );
              }
              return (
                <div key={i} className="rounded-xl border border-danger/40 bg-danger/5 px-4 py-3 text-xs text-danger">
                  {m.text}
                </div>
              );
            })}

            {pendingConfirmation && (
              <div className="rounded-xl border border-warn/50 bg-warn/10 px-4 py-3">
                <div className="mb-3 text-sm font-medium text-warn">
                  autoriser {pendingConfirmation.tool}({formatArgs(pendingConfirmation.args)}) ?
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => respondToConfirmation(true)}
                    className="flex-1 rounded-lg bg-ok py-2 text-sm font-medium text-void"
                  >
                    autoriser
                  </button>
                  <button
                    onClick={() => respondToConfirmation(false)}
                    className="flex-1 rounded-lg border border-danger py-2 text-sm text-danger"
                  >
                    refuser
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="flex-shrink-0 px-6 pb-6 pt-2">
          <div className="mx-auto max-w-3xl">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void sendMessage();
              }}
              className="flex items-end gap-2 rounded-2xl border border-border bg-panel px-3 py-2"
            >
              <button
                type="button"
                disabled
                title="pas encore disponible"
                className="cursor-not-allowed rounded-lg p-2 text-ink-dim opacity-40"
              >
                <PlusIcon />
              </button>

              <textarea
                ref={textareaRef}
                value={input}
                onChange={(e) => setInput(e.currentTarget.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    void sendMessage();
                  }
                }}
                placeholder="Écrire un message..."
                rows={1}
                disabled={sending || !!pendingConfirmation}
                className="max-h-[200px] flex-1 resize-none bg-transparent py-1.5 outline-none placeholder:text-ink-dim"
              />

              <div className="flex items-center gap-2 pb-1">
                {apiModel && (
                  <span className="hidden text-xs text-ink-dim sm:inline">{apiModel}</span>
                )}
                <button
                  type="submit"
                  disabled={sending || !!pendingConfirmation || !input.trim()}
                  className="rounded-full bg-accent p-2 text-white disabled:bg-transparent disabled:text-ink-dim disabled:opacity-40"
                >
                  <ArrowUpIcon />
                </button>
              </div>
            </form>
            <p className="mt-2 text-center text-[11px] text-ink-dim">
              Triton peut faire des erreurs. Vérifie les informations importantes.
            </p>
          </div>
        </div>
      </main>
    </div>
  );
}

export default App;
