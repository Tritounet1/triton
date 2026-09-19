import { describe, expect, it } from "vitest";
import { moveInFlightModel, setInFlightModel } from "./inFlightModels";

describe("in-flight model state", () => {
  it("adds, replaces, and removes the model for a request", () => {
    const started = setInFlightModel({}, "session-1", "google/gemini-3.1-flash");
    expect(started).toEqual({ "session-1": "google/gemini-3.1-flash" });

    const replaced = setInFlightModel(started, "session-1", "openai/gpt-image-1.5");
    expect(replaced).toEqual({ "session-1": "openai/gpt-image-1.5" });

    expect(setInFlightModel(replaced, "session-1", null)).toEqual({});
  });

  it("moves a new conversation model from the temporary key to its server id", () => {
    const moved = moveInFlightModel(
      { "": "google/gemini-3.1-flash", existing: "z-ai/glm-5.3-flash" },
      "",
      "server-session",
    );

    expect(moved).toEqual({
      existing: "z-ai/glm-5.3-flash",
      "server-session": "google/gemini-3.1-flash",
    });
    expect("" in moved).toBe(false);
  });

  it("leaves unrelated state untouched when there is no temporary request", () => {
    const previous = { existing: "z-ai/glm-5.3-flash" };
    expect(moveInFlightModel(previous, "", "server-session")).toBe(previous);
  });
});
