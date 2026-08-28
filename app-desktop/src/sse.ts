export interface SSEEvent {
  event: string;
  data: Record<string, unknown>;
}

/** Parse un flux Server-Sent Events depuis une réponse fetch en streaming.
 * Le navigateur n'a pas d'EventSource utilisable en POST, donc on lit le
 * corps de la réponse à la main. */
export async function* parseSSE(response: Response): AsyncGenerator<SSEEvent> {
  if (!response.body) return;

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let separatorIndex: number;
    while ((separatorIndex = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, separatorIndex);
      buffer = buffer.slice(separatorIndex + 2);

      let event = "message";
      let data = "";
      for (const line of rawEvent.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }

      if (data) {
        yield { event, data: JSON.parse(data) as Record<string, unknown> };
      }
    }
  }
}
