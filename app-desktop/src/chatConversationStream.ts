import { type ChatMsg } from "./chatMessages";
import { consumeChatStream } from "./chatStreamController";
import { objectField, optionalStringField, stringField } from "./chatStreamPayloads";
import { isAbortError, interruptedAssistantText, upsertAssistantMessage } from "./chatStreamState";
import { startChatStream, type ChatRequest } from "./chatTransport";

export interface PendingConfirmation {
  id: string;
  tool: string;
  args: Record<string, unknown>;
  sessionId: string;
}

interface ConversationSession {
  id: string;
  title: string | null;
  project_id: string | null;
  pinned: boolean;
}

export interface ChatConversationStreamOptions {
  request: ChatRequest;
  inFlightModel: string | null;
  initialSessionId: string | null;
  isDisplayed: (sessionId: string | null) => boolean;
  updateMessages: (updater: (messages: ChatMsg[]) => ChatMsg[]) => void;
  updateSessions: (updater: (sessions: ConversationSession[]) => ConversationSession[]) => void;
  setSessionCreated: (sessionId: string) => void;
  markSending: (sessionKey: string, isSending: boolean) => void;
  markInFlightModel: (sessionKey: string, model: string | null) => void;
  moveSendingKey: (from: string, to: string) => void;
  setFileRefreshTick: (updater: (tick: number) => number) => void;
  addPendingSubagent: (id: string) => void;
  setPendingConfirmation: (confirmation: PendingConfirmation | null) => void;
  pendingConfirmations: Map<string, PendingConfirmation>;
  abortControllers: Map<string, AbortController>;
  onStreamEvent: () => void;
  onStreamFinished: () => void;
  refreshSessions: () => void;
  notifyCompletion: (text: string) => void;
  startStream?: (request: ChatRequest, signal: AbortSignal) => Promise<Response>;
}

export async function runChatConversationStream(options: ChatConversationStreamOptions): Promise<void> {
  const startTime = performance.now();
  let currentSessionId = options.initialSessionId;
  let currentSessionKey = currentSessionId ?? "";
  let assistantText = "";
  let flushScheduled = false;
  const controller = new AbortController();
  const isDisplayed = () => options.isDisplayed(currentSessionId);
  const flush = () => {
    flushScheduled = false;
    if (!isDisplayed()) return;
    const text = assistantText;
    options.updateMessages((messages) => upsertAssistantMessage(messages, text));
  };
  const scheduleFlush = () => {
    if (flushScheduled) return;
    flushScheduled = true;
    requestAnimationFrame(flush);
  };

  options.markSending(currentSessionKey, true);
  options.markInFlightModel(currentSessionKey, options.inFlightModel);
  options.abortControllers.set(currentSessionKey, controller);

  try {
    const response = await (options.startStream ?? startChatStream)(options.request, controller.signal);
    await consumeChatStream(
      response,
      ({ event, data }) => {
        if (event === "session") {
          const id = stringField(data, "session_id");
          if (!id) return;
          const wasNew = currentSessionId === null;
          currentSessionId = id;
          if (wasNew) {
            options.moveSendingKey(currentSessionKey, id);
            const currentController = options.abortControllers.get(currentSessionKey);
            options.abortControllers.delete(currentSessionKey);
            currentSessionKey = id;
            if (currentController) options.abortControllers.set(id, currentController);
            if (options.isDisplayed(options.initialSessionId)) options.setSessionCreated(id);
          }
          return;
        }
        if (event === "title") {
          const title = stringField(data, "title");
          if (!currentSessionId) return;
          const id = currentSessionId;
          options.updateSessions((sessions) =>
            sessions.some((session) => session.id === id)
              ? sessions.map((session) => (session.id === id ? { ...session, title } : session))
              : [{ id, title, project_id: options.request.project_id, pinned: false }, ...sessions],
          );
          return;
        }
        if (event === "token") {
          assistantText += stringField(data, "text");
          scheduleFlush();
          return;
        }
        if (event === "tool_call") {
          if (isDisplayed()) {
            options.updateMessages((messages) => [
              ...messages,
              {
                kind: "tool",
                tool: stringField(data, "tool"),
                args: objectField(data, "args"),
                result: stringField(data, "result"),
                time: Date.now(),
                model: optionalStringField(data, "model"),
              },
            ]);
            options.setFileRefreshTick((tick) => tick + 1);
          }
          assistantText = "";
          if (stringField(data, "tool") === "dispatch_subagent") {
            const match = /\(id=([a-f0-9]+)\)/.exec(stringField(data, "result"));
            if (match?.[1]) options.addPendingSubagent(match[1]);
          }
          return;
        }
        if (event === "done") {
          if (!isDisplayed()) return;
          const model = stringField(data, "model");
          const content = stringField(data, "content");
          options.updateMessages((messages) => {
            const last = messages[messages.length - 1];
            return upsertAssistantMessage(
              messages,
              content || (last?.kind === "assistant" ? last.text : ""),
              model,
            );
          });
          return;
        }
        if (event === "confirmation_required") {
          const pending = {
            id: stringField(data, "confirmation_id"),
            tool: stringField(data, "tool"),
            args: objectField(data, "args"),
            sessionId: currentSessionKey,
          };
          options.pendingConfirmations.set(currentSessionKey, pending);
          if (isDisplayed()) options.setPendingConfirmation(pending);
          return;
        }
        if (event === "info" || event === "error") {
          if (!isDisplayed()) return;
          options.updateMessages((messages) => [
            ...messages,
            { kind: event, text: stringField(data, "message"), time: Date.now() },
          ]);
        }
      },
      () => {
        if (isDisplayed()) options.onStreamEvent();
      },
    );
  } catch (error) {
    if (isAbortError(error)) {
      if (isDisplayed()) {
        options.updateMessages((messages) =>
          upsertAssistantMessage(messages, interruptedAssistantText(assistantText)),
        );
      }
    } else if (isDisplayed()) {
      const networkFailure = error instanceof TypeError;
      options.updateMessages((messages) => [
        ...messages,
        {
          kind: "error",
          text: networkFailure
            ? "impossible de contacter l'API Triton (127.0.0.1:8000)."
            : `l'API Triton a répondu avec une erreur : ${error instanceof Error ? error.message : String(error)}`,
          time: Date.now(),
        },
      ]);
    }
  } finally {
    options.abortControllers.delete(currentSessionKey);
    options.pendingConfirmations.delete(currentSessionKey);
    options.markSending(currentSessionKey, false);
    options.markInFlightModel(currentSessionKey, null);
    if (isDisplayed()) options.setPendingConfirmation(null);
    if (isDisplayed()) options.onStreamFinished();
    options.refreshSessions();
    if (performance.now() - startTime > 15000) {
      options.notifyCompletion(
        assistantText ? assistantText.slice(0, 200) : "La réponse est prête.",
      );
    }
  }
}
