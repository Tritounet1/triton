import { describe, expect, it } from "vitest";
import { parseSSE } from "./sse";

function streamResponse(chunks: string[]): Response {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
  );
}

describe("parseSSE", () => {
  it("reassembles an event split across transport chunks", async () => {
    const events = [];
    for await (const event of parseSSE(
      streamResponse(['event: token\ndata: {"text":"Bon', 'jour"}\n\n']),
    )) events.push(event);

    expect(events).toEqual([{ event: "token", data: { text: "Bonjour" } }]);
  });

  it("keeps events distinct and ignores empty keep-alives", async () => {
    const events = [];
    for await (const event of parseSSE(
      streamResponse([':\n\nevent: token\ndata: {"text":"A"}\n\nevent: done\ndata: {"content":"A"}\n\n']),
    )) events.push(event);

    expect(events).toEqual([
      { event: "token", data: { text: "A" } },
      { event: "done", data: { content: "A" } },
    ]);
  });
});
