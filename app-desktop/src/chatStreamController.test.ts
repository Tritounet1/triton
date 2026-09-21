import { describe, expect, it, vi } from "vitest";
import { consumeChatStream } from "./chatStreamController";

describe("consumeChatStream", () => {
  it("delivers parsed events in order", async () => {
    const onEvent = vi.fn();
    await consumeChatStream(new Response('event: token\ndata: {"text":"ok"}\n\n'), onEvent);
    expect(onEvent).toHaveBeenCalledWith({ event: "token", data: { text: "ok" } });
  });

  it("surfaces a non-SSE HTTP error", async () => {
    await expect(consumeChatStream(new Response("unauthorized", { status: 401 }), vi.fn()))
      .rejects.toThrow("unauthorized");
  });
});
