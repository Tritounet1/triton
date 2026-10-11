import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SearchPage } from "./SearchPage";

const recentResults = [{
  id: "memory:global", kind: "memory", title: "Mémoire globale", excerpt: "Préférer TypeScript", project_id: null,
  project_name: null, session_id: null, task_id: null, path: null, modified_at: "2026-10-11T10:00:00+00:00",
}];

describe("SearchPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes("/search?") ? recentResults : []),
    } as Response)));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows recent notes before a query", async () => {
    render(<SearchPage onBack={vi.fn()} onSelectSession={vi.fn()} onSelectTask={vi.fn()} onSelectProject={vi.fn()} />);
    expect(await screen.findByText("Mémoire globale")).toBeInTheDocument();
    expect(screen.getByText("Notes récentes · 1")).toBeInTheDocument();
  });

  it("opens a conversation returned by global search", async () => {
    const onSelectSession = vi.fn();
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes("/search?") ? [{
        ...recentResults[0], id: "conversation:session-1", kind: "conversation", title: "Projet Triton", session_id: "session-1",
      }] : []),
    } as Response)));
    const user = userEvent.setup();
    render(<SearchPage onBack={vi.fn()} onSelectSession={onSelectSession} onSelectTask={vi.fn()} onSelectProject={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Recherche globale" }), "triton");
    await user.click(await screen.findByRole("button", { name: /Projet Triton/ }));
    expect(onSelectSession).toHaveBeenCalledWith("session-1");
  });
});
