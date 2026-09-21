import { describe, expect, it, vi } from "vitest";
import { consumeChatStream } from "./chatStreamController";
import type { SSEEvent } from "./sse";

describe("consumeChatStream", () => {
  it("delivers parsed events in order", async () => {
    const onEvent = vi.fn<(event: SSEEvent) => void>();
    await consumeChatStream(new Response('event: token\ndata: {"text":"ok"}\n\n'), onEvent);
    expect(onEvent).toHaveBeenCalledWith({ event: "token", data: { text: "ok" } });
  });

  it("surfaces a non-SSE HTTP error", async () => {
    await expect(consumeChatStream(new Response("unauthorized", { status: 401 }), vi.fn<(event: SSEEvent) => void>()))
      .rejects.toThrow("unauthorized");
  });

  it("can dispatch a stream directly to named handlers", async () => {
    const token = vi.fn();
    await consumeChatStream(new Response('event: token\ndata: {"text":"ok"}\n\n'), { token });
    expect(token).toHaveBeenCalledWith({ text: "ok" });
  });

  it("notifies activity for every received event", async () => {
    const activity = vi.fn();
    await consumeChatStream(new Response('event: token\ndata: {"text":"a"}\n\nevent: done\ndata: {}\n\n'), {}, activity);
    expect(activity).toHaveBeenCalledTimes(2);
  });
});
