import { afterEach, describe, expect, it, vi } from "vitest";
import { runChatConversationStream, type PendingConfirmation } from "./chatConversationStream";
import type { ChatMsg } from "./chatMessages";
import type { ChatRequest } from "./chatTransport";

const request: ChatRequest = {
  session_id: null,
  message: "Bonjour",
  project_id: "project-1",
  attachments: [],
  edit_turn_index: null,
  model: null,
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("runChatConversationStream", () => {
  it("applies a complete conversation stream to the local state", async () => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    let displayedSessionId: string | null = null;
    let messages: ChatMsg[] = [];
    let sessions: { id: string; title: string | null; project_id: string | null; pinned: boolean }[] = [];
    let refreshTick = 0;
    const pendingSubagents = new Set<string>();
    const confirmations = new Map<string, PendingConfirmation>();
    const controllers = new Map<string, AbortController>();
    const markSending = vi.fn();
    const markInFlightModel = vi.fn();
    const moveSendingKey = vi.fn();
    const onStreamEvent = vi.fn();
    const onStreamFinished = vi.fn();
    const refreshSessions = vi.fn();

    await runChatConversationStream({
      request,
      inFlightModel: "model-1",
      initialSessionId: null,
      isDisplayed: (sessionId) => displayedSessionId === sessionId,
      updateMessages: (updater) => {
        messages = updater(messages);
      },
      updateSessions: (updater) => {
        sessions = updater(sessions);
      },
      setSessionCreated: (sessionId) => {
        displayedSessionId = sessionId;
      },
      markSending,
      markInFlightModel,
      moveSendingKey,
      setFileRefreshTick: (updater) => {
        refreshTick = updater(refreshTick);
      },
      addPendingSubagent: (id) => pendingSubagents.add(id),
      setPendingConfirmation: vi.fn(),
      pendingConfirmations: confirmations,
      abortControllers: controllers,
      onStreamEvent,
      onStreamFinished,
      refreshSessions,
      notifyCompletion: vi.fn(),
      startStream: () =>
        Promise.resolve(new Response(
          [
            'event: session\ndata: {"session_id":"session-1"}',
            'event: title\ndata: {"title":"Premier échange"}',
            'event: token\ndata: {"text":"Bon"}',
            'event: token\ndata: {"text":"jour"}',
            'event: tool_call\ndata: {"tool":"dispatch_subagent","args":{},"result":"Lancé (id=abc123)"}',
            'event: done\ndata: {"content":"Bonjour !","model":"model-1"}',
          ].join("\n\n") + "\n\n",
        )),
    });

    expect(displayedSessionId).toBe("session-1");
    expect(sessions).toEqual([
      { id: "session-1", title: "Premier échange", project_id: "project-1", pinned: false },
    ]);
    expect(messages).toMatchObject([
      { kind: "assistant", text: "Bonjour" },
      { kind: "tool", tool: "dispatch_subagent" },
      { kind: "assistant", text: "Bonjour !", model: "model-1" },
    ]);
    expect(refreshTick).toBe(1);
    expect(pendingSubagents).toEqual(new Set(["abc123"]));
    expect(moveSendingKey).toHaveBeenCalledWith("", "session-1");
    expect(markSending).toHaveBeenNthCalledWith(1, "", true);
    expect(markSending).toHaveBeenLastCalledWith("session-1", false);
    expect(markInFlightModel).toHaveBeenLastCalledWith("session-1", null);
    expect(onStreamEvent).toHaveBeenCalledTimes(6);
    expect(onStreamFinished).toHaveBeenCalledOnce();
    expect(refreshSessions).toHaveBeenCalledOnce();
    expect(controllers).toEqual(new Map());
  });

  it("stores a confirmation for a conversation that is no longer displayed", async () => {
    const confirmations = new Map<string, PendingConfirmation>();
    const setPendingConfirmation = vi.fn();
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;

    const running = runChatConversationStream({
      request: { ...request, session_id: "session-1" },
      inFlightModel: "model-1",
      initialSessionId: "session-1",
      isDisplayed: () => false,
      updateMessages: vi.fn(),
      updateSessions: vi.fn(),
      setSessionCreated: vi.fn(),
      markSending: vi.fn(),
      markInFlightModel: vi.fn(),
      moveSendingKey: vi.fn(),
      setFileRefreshTick: vi.fn(),
      addPendingSubagent: vi.fn(),
      setPendingConfirmation,
      pendingConfirmations: confirmations,
      abortControllers: new Map(),
      onStreamEvent: vi.fn(),
      onStreamFinished: vi.fn(),
      refreshSessions: vi.fn(),
      notifyCompletion: vi.fn(),
      startStream: () =>
        Promise.resolve(
          new Response(
            new ReadableStream({
              start(controller) {
                streamController = controller;
              },
            }),
          ),
        ),
    });

    streamController?.enqueue(
      encoder.encode(
        'event: confirmation_required\ndata: {"confirmation_id":"confirm-1","tool":"write_file","args":{"path":"a.txt"}}\n\n',
      ),
    );
    await vi.waitFor(() => {
      expect(confirmations.get("session-1")).toMatchObject({
        id: "confirm-1",
        tool: "write_file",
      });
    });
    expect(setPendingConfirmation).not.toHaveBeenCalled();
    streamController?.close();
    await running;
    expect(confirmations).toEqual(new Map());
  });

  it("does not leave a stray empty assistant bubble after a tool-error abort", async () => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      return setTimeout(() => {
        callback(0);
      }, 0) as unknown as number;
    });
    let messages: ChatMsg[] = [];
    const encoder = new TextEncoder();
    let streamController: ReadableStreamDefaultController<Uint8Array> | undefined;

    const running = runChatConversationStream({
      request: { ...request, session_id: "session-1" },
      inFlightModel: "model-1",
      initialSessionId: "session-1",
      isDisplayed: () => true,
      updateMessages: (updater) => {
        messages = updater(messages);
      },
      updateSessions: vi.fn(),
      setSessionCreated: vi.fn(),
      markSending: vi.fn(),
      markInFlightModel: vi.fn(),
      moveSendingKey: vi.fn(),
      setFileRefreshTick: vi.fn(),
      addPendingSubagent: vi.fn(),
      setPendingConfirmation: vi.fn(),
      pendingConfirmations: new Map(),
      abortControllers: new Map(),
      onStreamEvent: vi.fn(),
      onStreamFinished: vi.fn(),
      refreshSessions: vi.fn(),
      notifyCompletion: vi.fn(),
      startStream: () =>
        Promise.resolve(
          new Response(
            new ReadableStream({
              start(controller) {
                streamController = controller;
              },
            }),
          ),
        ),
    });

    streamController?.enqueue(
      encoder.encode('event: token\ndata: {"text":"Oui, je peux chercher."}\n\n'),
    );
    streamController?.enqueue(
      encoder.encode(
        'event: tool_call\ndata: {"tool":"web_search","args":{},"result":"error: unsupported workspace tool","model":"model-1"}\n\n',
      ),
    );
    streamController?.enqueue(
      encoder.encode(
        'event: error\ndata: {"message":"6 appels d\'outils ont échoué d\'affilée."}\n\n',
      ),
    );
    streamController?.close();
    await running;
    await new Promise((resolve) => {
      setTimeout(resolve, 10);
    });

    expect(messages[messages.length - 1]).toMatchObject({ kind: "error" });
    const toolIndex = messages.findIndex((m) => m.kind === "tool");
    const trailing = messages.slice(toolIndex + 1);
    expect(trailing.some((m) => m.kind === "assistant" && m.text === "")).toBe(false);
  });
});
