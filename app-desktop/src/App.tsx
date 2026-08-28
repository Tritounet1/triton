import { useEffect, useRef, useState } from "react";
import { parseSSE } from "./sse";
import "./App.css";

const API_BASE = "http://127.0.0.1:8000";

type ChatMessage =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; model?: string; tokens?: number }
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
  const [sessionId, setSessionId] = useState<string | null>(() =>
    localStorage.getItem("triton_session_id"),
  );
  const [pendingConfirmation, setPendingConfirmation] = useState<PendingConfirmation | null>(
    null,
  );

  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_BASE}/health`)
      .then((r) => setApiOnline(r.ok))
      .catch(() => setApiOnline(false));
  }, []);

  useEffect(() => {
    // uniquement au démarrage, pour une session déjà connue (localStorage).
    // ne doit pas se redéclencher quand sendMessage() fixe sessionId lui-même
    // via l'événement "session", sinon ça part en course avec le streaming
    // en cours (fetch concurrent + setMessages qui écrase l'état en cours).
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((raw: RawSessionMessage[] | null) => {
        if (raw) setMessages(historyToMessages(raw));
      })
      .catch(() => {
        /* session locale introuvable côté serveur, on repart d'une conversation vide */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

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

  function startNewSession() {
    setSessionId(null);
    localStorage.removeItem("triton_session_id");
    setMessages([]);
  }

  return (
    <main className="app">
      <header className="topbar">
        <span className="title">Triton</span>
        <span className={`status ${apiOnline ? "online" : "offline"}`}>
          {apiOnline === null ? "connexion..." : apiOnline ? "API connectée" : "API hors ligne"}
        </span>
        <button className="new-session" onClick={startNewSession}>
          nouvelle conversation
        </button>
      </header>

      <div className="messages" ref={scrollRef}>
        {messages.length === 0 && (
          <p className="empty">Écris un message pour démarrer la conversation.</p>
        )}

        {messages.map((m, i) => {
          if (m.kind === "user") {
            return (
              <div key={i} className="bubble user">
                {m.text}
              </div>
            );
          }
          if (m.kind === "assistant") {
            return (
              <div key={i} className="bubble assistant">
                {m.text}
              </div>
            );
          }
          if (m.kind === "tool") {
            return (
              <div key={i} className="card tool">
                <div className="card-title">
                  outil : {m.tool}({formatArgs(m.args)})
                </div>
                <div className="card-body">{m.result}</div>
              </div>
            );
          }
          if (m.kind === "info") {
            return (
              <div key={i} className="card info">
                {m.text}
              </div>
            );
          }
          return (
            <div key={i} className="card error">
              {m.text}
            </div>
          );
        })}

        {pendingConfirmation && (
          <div className="card confirm">
            <div className="card-title">
              autoriser {pendingConfirmation.tool}({formatArgs(pendingConfirmation.args)}) ?
            </div>
            <div className="confirm-actions">
              <button className="approve" onClick={() => respondToConfirmation(true)}>
                autoriser
              </button>
              <button className="deny" onClick={() => respondToConfirmation(false)}>
                refuser
              </button>
            </div>
          </div>
        )}
      </div>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void sendMessage();
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.currentTarget.value)}
          placeholder="Écris à Triton..."
          disabled={sending || !!pendingConfirmation}
        />
        <button type="submit" disabled={sending || !!pendingConfirmation || !input.trim()}>
          envoyer
        </button>
      </form>
    </main>
  );
}

export default App;
