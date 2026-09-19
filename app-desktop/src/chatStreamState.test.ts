import { describe, expect, it } from "vitest";
import { interruptedAssistantText, isAbortError, upsertAssistantMessage } from "./chatStreamState";

describe("chat stream state", () => {
  it("keeps a partial response visible when a stream is cancelled", () => {
    expect(interruptedAssistantText("Bonjour")).toBe("Bonjour\n\n*(interrompu)*");
    expect(interruptedAssistantText("")).toBe("*(interrompu)*");
  });

  it("updates the current assistant message instead of adding a duplicate", () => {
    const result = upsertAssistantMessage(
      [{ kind: "assistant", text: "partiel", time: 1 }],
      "final",
      "google/gemini-3.1-flash",
    );
    expect(result).toEqual([{ kind: "assistant", text: "final", time: 1, model: "google/gemini-3.1-flash" }]);
  });

  it("recognizes only an AbortError as a user cancellation", () => {
    expect(isAbortError(new DOMException("cancelled", "AbortError"))).toBe(true);
    expect(isAbortError(new Error("network failed"))).toBe(false);
  });
});
