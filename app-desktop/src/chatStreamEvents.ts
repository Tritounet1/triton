import type { SSEEvent } from "./sse";

export type ChatStreamEventName = "session" | "title" | "token" | "tool_call" | "done" | "confirmation_required" | "info" | "error";

export type ChatStreamEventHandlers = Partial<Record<ChatStreamEventName, (data: Record<string, unknown>) => void>>;

export function dispatchChatStreamEvent(
  event: SSEEvent,
  handlers: ChatStreamEventHandlers,
): void {
  if (event.event in handlers) {
    handlers[event.event as ChatStreamEventName]?.(event.data);
  }
}
