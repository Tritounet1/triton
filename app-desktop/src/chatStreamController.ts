import { parseSSE, type SSEEvent } from "./sse";

export async function consumeChatStream(
  response: Response,
  onEvent: (event: SSEEvent) => void | Promise<void>,
): Promise<void> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `La requête de chat a échoué (${response.status}).`);
  }
  for await (const event of parseSSE(response)) {
    await onEvent(event);
  }
}
