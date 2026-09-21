import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WebAuthGate } from "./WebAuthGate";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WebAuthGate", () => {
  it("shows the application after a successful login", async () => {
    const user = userEvent.setup();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ authenticated: false }) })
      .mockResolvedValueOnce({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    render(
      <WebAuthGate>
        <p>Conversations</p>
      </WebAuthGate>,
    );

    await user.type(await screen.findByLabelText("Identifiant"), "admin");
    await user.type(screen.getByLabelText("Mot de passe"), "password");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Conversations")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/auth/login"),
      expect.objectContaining({
        body: JSON.stringify({ username: "admin", password: "password" }),
        credentials: "include",
        method: "POST",
      }),
    );
  });

  it("displays an invalid-credentials error", async () => {
    const user = userEvent.setup();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValueOnce({ ok: true, json: () => Promise.resolve({ authenticated: false }) })
        .mockResolvedValueOnce({ ok: false, status: 401 }),
    );

    render(
      <WebAuthGate>
        <p>Conversations</p>
      </WebAuthGate>,
    );

    await user.type(await screen.findByLabelText("Identifiant"), "admin");
    await user.type(screen.getByLabelText("Mot de passe"), "wrong");
    await user.click(screen.getByRole("button", { name: "Se connecter" }));

    expect(await screen.findByText("Identifiants incorrects.")).toBeInTheDocument();
  });
});
