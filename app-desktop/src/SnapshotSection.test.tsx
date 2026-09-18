import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SnapshotSection } from "./SnapshotSection";
import type { SnapshotPoint } from "./snapshotDiff";

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({
    ok,
    json: () => Promise.resolve(body),
  } as Response);
}

function mockFetch(points: SnapshotPoint[]) {
  return vi.fn((input: string | URL | Request) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/snapshots")) return jsonResponse(points);
    return jsonResponse(null, false);
  });
}

const onePoint: SnapshotPoint[] = [
  { turn_index: 1, kind: "content", created_at: "2026-01-01T00:00:00Z", message_preview: "first write" },
];

const twoPoints: SnapshotPoint[] = [
  { turn_index: 1, kind: "content", created_at: "2026-01-01T00:00:00Z", message_preview: "first write" },
  { turn_index: 3, kind: "content", created_at: "2026-01-01T00:05:00Z", message_preview: "later write" },
];

describe("SnapshotSection", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch([]));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when sessionId is null", () => {
    const { container } = render(
      <SnapshotSection sessionId={null} onOpenHistory={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while there are no snapshot points for the session", async () => {
    vi.stubGlobal("fetch", mockFetch([]));
    const { container } = render(
      <SnapshotSection sessionId="s1" onOpenHistory={vi.fn()} />,
    );
    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the banner and history button once the session has a snapshot", async () => {
    vi.stubGlobal("fetch", mockFetch(onePoint));
    render(<SnapshotSection sessionId="s1" onOpenHistory={vi.fn()} />);

    expect(
      await screen.findByText("1 sauvegarde interne disponible"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Voir l'historique" })).toBeInTheDocument();
  });

  it("still shows a single history button with several snapshot points", async () => {
    // regression check for the "bandeau filet de securite qui se
    // chevauchait sur 3 colonnes" bug this session - the banner must not
    // grow a button per restore point, it always opens the same history
    // browser regardless of how many points exist (see
    // SnapshotHistoryView.tsx).
    vi.stubGlobal("fetch", mockFetch(twoPoints));
    render(<SnapshotSection sessionId="s1" onOpenHistory={vi.fn()} />);

    expect(await screen.findByRole("button", { name: "Voir l'historique" })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("calls onOpenHistory when the button is clicked", async () => {
    const user = userEvent.setup();
    const onOpenHistory = vi.fn();
    vi.stubGlobal("fetch", mockFetch(onePoint));
    render(<SnapshotSection sessionId="s1" onOpenHistory={onOpenHistory} />);

    await user.click(await screen.findByRole("button", { name: "Voir l'historique" }));

    expect(onOpenHistory).toHaveBeenCalledTimes(1);
  });
});
