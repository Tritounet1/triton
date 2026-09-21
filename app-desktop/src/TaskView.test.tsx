import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TaskView } from "./TaskView";

const runningTask = {
  id: "task-1", session_id: "s1", name: "Serveur", command: "pnpm dev",
  directory: "/tmp/project", status: "running", exit_code: null,
  created_at: "2026-09-21T10:00:00Z", logs: "Listening on 3000",
};

describe("TaskView", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn((_input: string, init?: RequestInit) => Promise.resolve({
      ok: true,
      json: () => Promise.resolve(init?.method === "POST" ? { ...runningTask, status: "stopped" } : runningTask),
    } as Response)));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("loads task output and stops a running task", async () => {
    const user = userEvent.setup();
    render(<TaskView taskId="task-1" onBack={vi.fn()} />);
    expect(await screen.findByText("Listening on 3000")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Arrêter" }));
    await waitFor(() => { expect(fetch).toHaveBeenCalledWith(
      "http://127.0.0.1:8000/background_tasks/task-1/stop", { method: "POST" },
    ); });
    expect(await screen.findByText("arrêtée")).toBeInTheDocument();
  });
});
