import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SearchPage } from "./SearchPage";

const sessions = [
  { id: "2026-09-01_120000", title: "Projet Triton", project_id: null },
  { id: "2026-09-02_120000", title: "Interne", project_id: "project-1" },
];

describe("SearchPage", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(url.includes("/search?") ? [] : sessions),
    } as Response)));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("finds a top-level conversation by title and opens it", async () => {
    const user = userEvent.setup();
    const onSelectSession = vi.fn();
    render(<SearchPage onBack={vi.fn()} onSelectSession={onSelectSession} />);
    await user.type(await screen.findByRole("textbox", { name: "Rechercher une conversation" }), "triton");
    await user.click(await screen.findByRole("button", { name: "Projet Triton" }));
    expect(onSelectSession).toHaveBeenCalledWith("2026-09-01_120000");
    expect(screen.queryByText("Interne")).not.toBeInTheDocument();
  });
});
