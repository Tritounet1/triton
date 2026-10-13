import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HomeHero } from "./HomeHero";

describe("HomeHero", () => {
  it("offers code suggestions only inside a project", () => {
    const { unmount } = render(<HomeHero projectName={null} onPick={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Explorer le dépôt/ })).toBeNull();
    expect(screen.getByRole("button", { name: /Veille web/ })).toBeInTheDocument();
    unmount();

    render(<HomeHero projectName="api-billing" onPick={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Explorer le dépôt/ })).toBeInTheDocument();
    expect(screen.getByText("Projet api-billing")).toBeInTheDocument();
  });

  it("fills the composer with the picked suggestion", async () => {
    const user = userEvent.setup();
    const onPick = vi.fn();
    render(<HomeHero projectName="api-billing" onPick={onPick} />);
    await user.click(screen.getByRole("button", { name: /Écrire des tests/ }));
    expect(onPick).toHaveBeenCalledWith(
      "Ajoute des tests de régression pour les derniers changements de ce projet.",
    );
  });
});
