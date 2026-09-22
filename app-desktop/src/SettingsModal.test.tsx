import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SettingsModal } from "./SettingsModal";

describe("SettingsModal", () => {
  it("shows only remote-safe settings in the web deployment", () => {
    render(
      <SettingsModal
        isOpen
        isWebDeployment
        onClose={vi.fn()}
        onModelChanged={vi.fn()}
        onImageModelChanged={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Modèle")).toHaveLength(2);
    expect(screen.getByText("Génération d’images")).toBeInTheDocument();
    expect(screen.queryByText("Clé API")).toBeNull();
    expect(screen.queryByText("Serveurs MCP")).toBeNull();
  });
});
