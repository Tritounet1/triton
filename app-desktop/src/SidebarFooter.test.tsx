import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SidebarFooter } from "./SidebarFooter";

describe("SidebarFooter", () => {
  it("opens settings and toggles the theme", async () => {
    const user = userEvent.setup();
    const onOpenSettings = vi.fn();
    const onToggleTheme = vi.fn();
    render(
      <SidebarFooter
        isWebDeployment={false}
        themeMode="light"
        onOpenSettings={onOpenSettings}
        onToggleTheme={onToggleTheme}
      />,
    );

    expect(screen.getByText("Triton Desktop")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Paramètres" }));
    await user.click(screen.getByRole("button", { name: "Passer en thème sombre" }));
    expect(onOpenSettings).toHaveBeenCalledOnce();
    expect(onToggleTheme).toHaveBeenCalledOnce();
  });

  it("shows the web instance host", () => {
    render(
      <SidebarFooter
        isWebDeployment
        themeMode="dark"
        onOpenSettings={vi.fn()}
        onToggleTheme={vi.fn()}
      />,
    );
    expect(screen.getByText("Instance web")).toBeInTheDocument();
    expect(screen.getByText(window.location.host)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Passer en thème clair" })).toBeInTheDocument();
  });
});
