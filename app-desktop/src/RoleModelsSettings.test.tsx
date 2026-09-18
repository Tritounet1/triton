import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RoleModelsSettings } from "./RoleModelsSettings";

function jsonResponse(body: unknown, ok = true) {
  return Promise.resolve({ ok, json: () => Promise.resolve(body) } as Response);
}

const initialRoles = [
  {
    role: "orchestrator",
    default_model: "anthropic/claude-sonnet-5",
    model: "anthropic/claude-sonnet-5",
    is_override: true,
  },
  {
    role: "code",
    default_model: "deepseek/deepseek-v4-flash",
    model: "deepseek/deepseek-v4-flash",
    is_override: false,
  },
];

const models = [
  {
    id: "anthropic/claude-sonnet-5",
    name: "Claude Sonnet 5",
    supports_tools: true,
  },
  {
    id: "deepseek/deepseek-v4-flash",
    name: "DeepSeek V4 Flash",
    supports_tools: true,
  },
  {
    id: "google/gemini-3.7-flash",
    name: "Gemini 3.7 Flash",
    supports_tools: true,
  },
  {
    id: "amazon/nova-2-lite-v1",
    name: "Nova 2 Lite",
    supports_tools: true,
  },
];

function mockFetch() {
  let roles = initialRoles.map((role) => ({ ...role }));
  return vi.fn((input: string | URL | Request, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/openrouter/models")) return jsonResponse(models);
    if (url.endsWith("/settings/role_models") && init?.method === "PUT") {
      const body = JSON.parse(init.body as string) as { role: string; model: string | null };
      roles = roles.map((role) =>
        role.role === body.role
          ? {
              ...role,
              model: body.model ?? role.default_model,
              is_override: body.model !== null,
            }
          : role,
      );
      return jsonResponse(roles);
    }
    if (url.endsWith("/settings/role_models")) return jsonResponse(roles);
    return jsonResponse(null, false);
  });
}

describe("RoleModelsSettings", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", mockFetch());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("represents each selected model with its provider logo", async () => {
    render(<RoleModelsSettings />);

    const planner = await screen.findByRole("button", {
      name: "Modèle du rôle Planificateur",
    });
    const code = screen.getByRole("button", { name: "Modèle du rôle Code" });

    expect(planner).toHaveTextContent("Claude Sonnet 5");
    expect(code).toHaveTextContent("DeepSeek V4 Flash");
    expect(planner.querySelector('img[src="/anthropic-logo.png"]')).not.toBeNull();
    expect(code.querySelector('img[src="/deepseek-logo.png"]')).not.toBeNull();
    expect(screen.getByText("2 rôles")).toBeInTheDocument();
  });

  it("changes and resets a role model from the searchable selector", async () => {
    const user = userEvent.setup();
    render(<RoleModelsSettings />);

    const code = await screen.findByRole("button", { name: "Modèle du rôle Code" });
    await user.click(code);
    const codeOptions = await screen.findByRole("listbox", { name: "Modèle du rôle Code" });
    expect(within(codeOptions).queryByText("Nova 2 Lite")).not.toBeInTheDocument();
    expect(within(codeOptions).queryByText("Amazon (Nova)")).not.toBeInTheDocument();
    await user.click(within(codeOptions).getByText("Gemini 3.7 Flash"));

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8000/settings/role_models",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ role: "code", model: "google/gemini-3.7-flash" }),
        }),
      );
    });

    const plannerCard = screen.getByText("Planificateur").closest("section");
    if (!plannerCard) throw new Error("planner card not found");
    const reset = within(plannerCard).getByRole("button", {
      name: "Réinitialiser sur anthropic/claude-sonnet-5",
    });
    await user.click(reset);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        "http://127.0.0.1:8000/settings/role_models",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ role: "orchestrator", model: null }),
        }),
      );
    });
  });
});
