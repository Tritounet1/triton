import { parseSSE, type SSEEvent } from "./sse";
import { dispatchChatStreamEvent, type ChatStreamEventHandlers } from "./chatStreamEvents";

export async function consumeChatStream(
  response: Response,
  onEvent: ((event: SSEEvent) => void | Promise<void>) | ChatStreamEventHandlers,
  onAnyEvent?: () => void,
): Promise<void> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `La requête de chat a échoué (${response.status}).`);
  }
  for await (const event of parseSSE(response)) {
    onAnyEvent?.();
    if (typeof onEvent === "function") await onEvent(event);
    else dispatchChatStreamEvent(event, onEvent);
  }
}
