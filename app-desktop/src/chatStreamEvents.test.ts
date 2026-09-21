import { describe, expect, it, vi } from "vitest";
import { dispatchChatStreamEvent } from "./chatStreamEvents";

describe("dispatchChatStreamEvent", () => {
  it("routes known SSE events and ignores unknown events", () => {
    const token = vi.fn();
    dispatchChatStreamEvent({ event: "token", data: { text: "bonjour" } }, { token });
    dispatchChatStreamEvent({ event: "keepalive", data: {} }, { token });
    expect(token).toHaveBeenCalledTimes(1);
    expect(token).toHaveBeenCalledWith({ text: "bonjour" });
  });
});
