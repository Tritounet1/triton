import { render, screen, waitFor, within } from "@testing-library/react";
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

/** Route un fetch mock selon l'URL appelee, pour simuler les deux
 * endpoints que SnapshotSection interroge (liste des points, puis diff
 * d'un point precis une fois la confirmation ouverte). */
function mockFetch({
  points,
  diff = null,
  restoreOk = true,
}: {
  points: SnapshotPoint[];
  diff?: unknown;
  restoreOk?: boolean;
}) {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/snapshot/restore")) {
      void init;
      return jsonResponse({}, restoreOk);
    }
    if (url.includes("/snapshot/diff")) {
      return jsonResponse(diff);
    }
    if (url.includes("/snapshots")) {
      return jsonResponse(points);
    }
    return jsonResponse(null, false);
  });
}

const onePoint: SnapshotPoint[] = [
  { turn_index: 1, kind: "git", created_at: "2026-01-01T00:00:00Z", message_preview: "first write" },
];

const twoPoints: SnapshotPoint[] = [
  { turn_index: 1, kind: "git", created_at: "2026-01-01T00:00:00Z", message_preview: "first write" },
  { turn_index: 3, kind: "git", created_at: "2026-01-01T00:05:00Z", message_preview: "later write" },
];

describe("SnapshotSection", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch({ points: [] }));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders nothing when sessionId is null", () => {
    const { container } = render(<SnapshotSection sessionId={null} onRestored={vi.fn()} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while there are no snapshot points for the session", async () => {
    vi.stubGlobal("fetch", mockFetch({ points: [] }));
    const { container } = render(<SnapshotSection sessionId="s1" onRestored={vi.fn()} />);
    await waitFor(() => {
      expect(fetch).toHaveBeenCalled();
    });
    expect(container).toBeEmptyDOMElement();
  });

  it("shows a single 'Restaurer' action when there is only one snapshot point", async () => {
    vi.stubGlobal("fetch", mockFetch({ points: onePoint }));
    render(<SnapshotSection sessionId="s1" onRestored={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Restaurer" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Dernier message" })).not.toBeInTheDocument();
  });

  it("shows both undo actions when there are multiple snapshot points", async () => {
    // regression check for the "bandeau filet de securite qui se
    // chevauchait sur 3 colonnes" bug this session: both actions must be
    // present (and the banner must not crash/collapse) once a session has
    // written in more than one turn.
    vi.stubGlobal("fetch", mockFetch({ points: twoPoints }));
    render(<SnapshotSection sessionId="s1" onRestored={vi.fn()} />);
    // accessible name comes from Button's `label` prop, not its visible
    // children (see Button.tsx) - "Dernier message"/"Toute la session" are
    // the visible text, "Annuler le..." the label.
    expect(
      await screen.findByRole("button", { name: "Annuler le dernier message" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Annuler toute la session" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Filet de sécurité actif pour cette session")).toBeInTheDocument();
  });

  it("opens a confirmation dialog describing an irreversible restore when clicked", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockFetch({ points: onePoint }));
    render(<SnapshotSection sessionId="s1" onRestored={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Restaurer" }));

    expect(
      await screen.findByText("Restaurer l'état d'avant cette session ?"),
    ).toBeInTheDocument();
  });

  it("calls onRestored after a successful restore", async () => {
    const user = userEvent.setup();
    const onRestored = vi.fn();
    vi.stubGlobal("fetch", mockFetch({ points: onePoint, restoreOk: true }));
    render(<SnapshotSection sessionId="s1" onRestored={onRestored} />);

    await user.click(await screen.findByRole("button", { name: "Restaurer" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Restaurer" }));

    await waitFor(() => {
      expect(onRestored).toHaveBeenCalledTimes(1);
    });
  });
});
