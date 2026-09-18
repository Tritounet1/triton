import { describe, expect, it } from "vitest";
import { richCardFromToolCall } from "./richCardData";

describe("richCardFromToolCall", () => {
  it("builds a place-search map card", () => {
    const card = richCardFromToolCall("show_map", { place: "La Rochelle" });
    expect(card).toEqual({
      kind: "map",
      title: "La Rochelle",
      url: "https://www.google.com/maps/search/?api=1&query=La%20Rochelle",
    });
  });

  it("builds a directions map card, preferring origin/destination over place", () => {
    const card = richCardFromToolCall("show_map", {
      origin: "Paris",
      destination: "La Rochelle",
      place: "ignored",
    });
    expect(card?.kind).toBe("map");
    expect(card?.subtitle).toBe("Paris → La Rochelle");
    expect(card?.url).toContain("maps/dir/?api=1");
  });

  it("returns null for show_map with no usable args", () => {
    expect(richCardFromToolCall("show_map", {})).toBeNull();
    expect(richCardFromToolCall("show_map", { origin: "Paris" })).toBeNull();
  });

  it("builds a link preview card, falling back to the url as title", () => {
    const withTitle = richCardFromToolCall("show_link_preview", {
      url: "https://example.com",
      title: "Example",
      description: "A page",
    });
    expect(withTitle).toEqual({
      kind: "link",
      title: "Example",
      subtitle: "A page",
      url: "https://example.com",
    });

    const withoutTitle = richCardFromToolCall("show_link_preview", {
      url: "https://example.com",
    });
    expect(withoutTitle?.title).toBe("https://example.com");
  });

  it("returns null for an unrelated tool or a link preview with no url", () => {
    expect(richCardFromToolCall("read_file", { path: "x" })).toBeNull();
    expect(richCardFromToolCall("show_link_preview", { title: "x" })).toBeNull();
  });
});
