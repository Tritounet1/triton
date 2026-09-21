import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { RichCard } from "./RichCard";

const { openUrl } = vi.hoisted(() => ({
  openUrl: vi.fn<(_: string) => Promise<void>>(),
}));

vi.mock("@tauri-apps/plugin-opener", () => ({ openUrl }));

afterEach(() => {
  delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__;
  openUrl.mockReset();
});

describe("RichCard", () => {
  it("renders a standard external link in a browser", () => {
    render(
      <RichCard
        card={{
          kind: "map",
          title: "Itinéraire",
          url: "https://www.google.com/maps/dir/?api=1",
        }}
      />,
    );

    expect(screen.getByRole("link", { name: /itinéraire/i })).toHaveAttribute(
      "href",
      "https://www.google.com/maps/dir/?api=1",
    );
  });

  it("uses the native opener in Tauri", async () => {
    (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {};
    const user = userEvent.setup();
    render(
      <RichCard
        card={{ kind: "link", title: "Example", url: "https://example.com" }}
      />,
    );

    await user.click(screen.getByRole("link", { name: /ouvrir example/i }));

    expect(openUrl).toHaveBeenCalledWith("https://example.com");
  });
});
