import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { WebAccountsModal } from "./WebAccountsModal";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("WebAccountsModal", () => {
  it("lets an administrator create a member and sign out", async () => {
    const user = userEvent.setup();
    const onSignedOut = vi.fn();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve([{ id: "admin-id", username: "admin", role: "admin" }]),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ id: "member-id", username: "member", role: "member" }),
      })
      .mockResolvedValueOnce({ ok: true });
    vi.stubGlobal("fetch", fetchMock);

    render(<WebAccountsModal isOpen onClose={vi.fn()} onSignedOut={onSignedOut} />);

    expect(await screen.findByLabelText(/Identifiant/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Identifiant/), "member");
    await user.type(screen.getByLabelText(/Mot de passe/), "a-long-enough-password");
    await user.click(screen.getByRole("button", { name: "Créer le compte" }));

    expect((await screen.findAllByText("member")).length).toBe(2);
    await user.click(screen.getByRole("button", { name: "Se déconnecter" }));

    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      expect.stringContaining("/accounts"),
      expect.objectContaining({
        body: JSON.stringify({ username: "member", password: "a-long-enough-password", role: "member" }),
        credentials: "include",
        method: "POST",
      }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      3,
      expect.stringContaining("/auth/logout"),
      expect.objectContaining({ credentials: "include", method: "POST" }),
    );
    expect(onSignedOut).toHaveBeenCalledOnce();
  });

  it("hides administration controls from a member", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 403 }));

    render(<WebAccountsModal isOpen onClose={vi.fn()} onSignedOut={vi.fn()} />);

    expect(await screen.findByText("Seul un administrateur peut gérer les comptes.")).toBeInTheDocument();
    expect(screen.queryByText("Ajouter un compte")).toBeNull();
  });
});
