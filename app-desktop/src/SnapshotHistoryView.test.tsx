import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SnapshotHistoryView } from "./SnapshotHistoryView";
import type { SnapshotDiff, SnapshotFileContent, SnapshotPoint } from "./snapshotDiff";

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(body),
  } as Response);
}

const points: SnapshotPoint[] = [
  { turn_index: 1, kind: "content", created_at: "2026-01-01T00:00:00Z", message_preview: "first write" },
  { turn_index: 2, kind: "content", created_at: "2026-01-02T00:00:00Z", message_preview: "second write" },
];

const diffByTurn: Record<number, SnapshotDiff> = {
  1: { created: ["b.txt"], deleted: [], modified: [] },
  2: { created: [], deleted: [], modified: ["a.txt"] },
};

const contentByPath: Record<string, SnapshotFileContent> = {
  "a.txt": { old: "line1", new: "line1 edited" },
  "b.txt": { old: null, new: "brand new file" },
};

/** Route un fetch mock selon l'URL/methode appelee, pour simuler les
 * quatre endpoints que SnapshotHistoryView interroge (liste des points,
 * diff d'un tour, contenu avant/apres d'un fichier, restore). */
function mockFetch({ restoreOk = true }: { restoreOk?: boolean } = {}) {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/snapshot/restore")) {
      void init;
      return jsonResponse({ ok: true }, restoreOk);
    }
    if (url.includes("/snapshot/file")) {
      const path = new URL(url).searchParams.get("path") ?? "";
      return jsonResponse(contentByPath[path] ?? { old: null, new: null });
    }
    if (url.includes("/snapshot/diff")) {
      const turnIndex = Number(new URL(url).searchParams.get("turn_index"));
      return jsonResponse(diffByTurn[turnIndex] ?? { created: [], deleted: [], modified: [] });
    }
    if (url.includes("/snapshots")) {
      return jsonResponse(points);
    }
    return jsonResponse(null, false);
  });
}

describe("SnapshotHistoryView", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists commits newest first and auto-selects the most recent one's files", async () => {
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={vi.fn()} />);

    const rows = await screen.findAllByText(/write$/);
    expect(rows.map((el) => el.textContent)).toEqual(["second write", "first write"]);

    // turn 2 (newest) is auto-selected - its diff (a.txt modified) drives
    // the changed-files column.
    expect(await screen.findByText("a.txt")).toBeInTheDocument();
    expect(screen.queryByText("b.txt")).not.toBeInTheDocument();
  });

  it("shows a type badge per changed file", async () => {
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={vi.fn()} />);

    await screen.findByText("a.txt");
    expect(screen.getByText("M")).toBeInTheDocument();
  });

  it("reloads the changed files when a different commit is selected", async () => {
    const user = userEvent.setup();
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={vi.fn()} />);

    await screen.findByText("a.txt");
    await user.click(screen.getByText("first write"));

    expect(await screen.findByText("b.txt")).toBeInTheDocument();
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.queryByText("a.txt")).not.toBeInTheDocument();
  });

  it("shows the selected file's before/after content in red/green", async () => {
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={vi.fn()} />);

    await screen.findByText("a.txt");

    expect(await screen.findByText("line1")).toHaveClass("text-error");
    expect(await screen.findByText("line1 edited")).toHaveClass("text-success");
  });

  it("shows only the added content for a newly created file (no old block)", async () => {
    const user = userEvent.setup();
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={vi.fn()} />);

    await screen.findByText("a.txt");
    await user.click(screen.getByText("first write"));
    await user.click(await screen.findByText("b.txt"));

    expect(await screen.findByText("brand new file")).toHaveClass("text-success");
  });

  it("restores to the selected point on confirmation and notifies the parent", async () => {
    const user = userEvent.setup();
    const onRestored = vi.fn();
    render(<SnapshotHistoryView sessionId="s1" onBack={vi.fn()} onRestored={onRestored} />);

    await screen.findByText("a.txt");
    await user.click(screen.getByRole("button", { name: "Restaurer à ce point" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/second write/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Restaurer" }));

    await waitFor(() => {
      expect(onRestored).toHaveBeenCalledTimes(1);
    });
  });

  it("calls onBack when the back button is clicked", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    render(<SnapshotHistoryView sessionId="s1" onBack={onBack} onRestored={vi.fn()} />);

    await user.click(screen.getByRole("button", { name: "Retour" }));

    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
