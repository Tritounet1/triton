import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemorySettings } from "./MemorySettings";

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

const projects = [{ id: "p1", name: "Demo project" }];
const contentByUrl: Record<string, string> = {
  "http://127.0.0.1:8000/memory/global": "- global note",
  "http://127.0.0.1:8000/projects/p1/memory": "- project note",
};

function mockFetch() {
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (init?.method === "PUT") {
      const body = JSON.parse(init.body as string) as { content: string };
      return jsonResponse({ content: body.content });
    }
    if (url.includes("/projects") && url.endsWith("/memory")) {
      return jsonResponse({ content: contentByUrl[url] ?? "" });
    }
    if (url.endsWith("/projects")) return jsonResponse(projects);
    if (url.endsWith("/sessions")) return jsonResponse([]);
    if (url.includes("/memory/global")) return jsonResponse({ content: contentByUrl[url] ?? "" });
    return jsonResponse(null, false);
  });
}

describe("MemorySettings", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads and shows the global memory content", async () => {
    render(<MemorySettings />);
    expect(await screen.findByDisplayValue("- global note")).toBeInTheDocument();
  });

  it("loads a project's memory once picked", async () => {
    const user = userEvent.setup();
    render(<MemorySettings />);

    await user.click(screen.getByRole("combobox", { name: "Projet" }));
    await user.click(await screen.findByText("Demo project"));

    expect(await screen.findByDisplayValue("- project note")).toBeInTheDocument();
  });

  it("saves edited global memory content", async () => {
    const user = userEvent.setup();
    render(<MemorySettings />);

    const textarea = await screen.findByDisplayValue("- global note");
    await user.clear(textarea);
    await user.type(textarea, "- edited note");
    await user.click(screen.getByRole("button", { name: "Sauvegarder" }));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8000/memory/global",
        expect.objectContaining({ method: "PUT" }),
      );
    });
  });
});
