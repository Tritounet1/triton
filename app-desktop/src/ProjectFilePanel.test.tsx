import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProjectFilePanel } from "./ProjectFilePanel";

describe("ProjectFilePanel", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve({ ok: false, status: 403 } as Response)));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows a clear error when the project tree cannot be read", async () => {
    render(<ProjectFilePanel projectId="p1" projectName="Projet" folderPath="/tmp/projet" refreshSignal={0} sessionId={null} onOpenHistory={vi.fn()} tasks={[]} onOpenTask={vi.fn()} onStopTask={vi.fn()} onDeleteTask={vi.fn()} onOpenFile={vi.fn()} />);
    expect(await screen.findByText("dossier introuvable ou inaccessible.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("http://127.0.0.1:8000/projects/p1/tree");
  });
});
