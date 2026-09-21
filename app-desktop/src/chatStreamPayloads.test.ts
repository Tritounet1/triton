import { describe, expect, it } from "vitest";
import { optionalStringField, stringField } from "./chatStreamPayloads";

describe("chat stream payloads", () => {
  it("normalizes untrusted SSE scalar fields", () => {
    expect(stringField({ text: "hello" }, "text")).toBe("hello");
    expect(stringField({ text: 42 }, "text")).toBe("");
    expect(optionalStringField({ model: "google/gemini" }, "model")).toBe("google/gemini");
    expect(optionalStringField({ model: {} }, "model")).toBeUndefined();
  });
});
