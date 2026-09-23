import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { McpSettings } from "./McpSettings";

const servers = [
  {
    name: "mcp-notes",
    command: "npx",
    args: [
      "mcp-remote",
      "https://notes.example.test/mcp",
      "--header",
      "Authorization: Bearer super-secret-token",
    ],
    enabled: true,
    connected: true,
    error: null,
    tools: ["list_documents", "get_document"],
  },
  {
    name: "local-search",
    command: "uvx",
    args: ["search-mcp"],
    enabled: false,
    connected: false,
    error: null,
    tools: [],
  },
];

function jsonResponse(body: unknown) {
  return Promise.resolve({ ok: true, json: () => Promise.resolve(body) } as Response);
}

describe("McpSettings", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(() => jsonResponse(servers)));
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("presents each server with its state, command and available tools", async () => {
    render(<McpSettings />);

    expect(await screen.findByText("2 serveurs")).toBeInTheDocument();
    expect(screen.getByText("mcp-notes")).toBeInTheDocument();
    expect(screen.getByText("2 outils")).toBeInTheDocument();
    expect(screen.getByText("désactivé")).toBeInTheDocument();
    expect(screen.getByText("list_documents · get_document")).toBeInTheDocument();
    expect(
      screen.getByText("npx mcp-remote https://notes.example.test/mcp --header Authorization: Bearer ••••••••"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/super-secret-token/)).not.toBeInTheDocument();
  });

  it("opens and closes the add-server form from the dedicated action", async () => {
    const user = userEvent.setup();
    render(<McpSettings />);

    await screen.findByText("2 serveurs");
    await user.click(screen.getByRole("button", { name: "Ajouter un serveur" }));

    expect(screen.getByText("Nouveau serveur MCP")).toBeInTheDocument();
    expect(screen.getByLabelText("Nom")).toBeInTheDocument();
    expect(screen.getByLabelText("Commande")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Annuler" }));
    expect(screen.queryByText("Nouveau serveur MCP")).not.toBeInTheDocument();
  });

  it("edits an existing server through PATCH instead of deleting and re-adding it", async () => {
    const user = userEvent.setup();
    const calls: { url: string; method: string; body: unknown }[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init?: RequestInit) => {
        calls.push({
          url,
          method: init?.method ?? "GET",
          body: init?.body ? JSON.parse(init.body as string) : null,
        });
        return jsonResponse(servers);
      }),
    );
    render(<McpSettings />);

    await screen.findByText("2 serveurs");
    const editButtons = screen.getAllByRole("button", { name: "Modifier" });
    const secondEditButton = editButtons[1];
    if (!secondEditButton) throw new Error("expected a second Modifier button");
    await user.click(secondEditButton);

    expect(screen.getByText("Modifier « local-search »")).toBeInTheDocument();
    expect(screen.getByLabelText("Nom")).toHaveValue("local-search");
    expect(screen.getByLabelText("Commande")).toHaveValue("uvx");
    expect(screen.getByLabelText("Arguments (un par ligne)")).toHaveValue("search-mcp");
    expect(screen.getByLabelText("Variables d'environnement (CLE=valeur, une par ligne)")).toHaveValue("");

    await user.click(screen.getByRole("button", { name: "Enregistrer" }));

    const patchCall = calls.find((c) => c.method === "PATCH");
    expect(patchCall?.url).toBe("http://127.0.0.1:8000/mcp/servers/local-search");
    expect(patchCall?.body).toMatchObject({
      name: "local-search",
      command: "uvx",
      args: ["search-mcp"],
      enabled: false,
    });
  });
});
