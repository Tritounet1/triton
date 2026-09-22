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
    expect(screen.queryByText("Serveurs MCP")).toBeNull();
    expect(screen.getByText("Mémoire")).toBeInTheDocument();
    expect(screen.getByText("Logs & coûts")).toBeInTheDocument();
    expect(screen.getByText("Sauvegarde")).toBeInTheDocument();
    expect(screen.queryByText("Tavily")).toBeNull();
    expect(screen.queryByText("Clé API")).toBeNull();
    expect(screen.queryByText("Rôles multi-agent")).toBeNull();
    expect(screen.queryByText("Tâches récurrentes")).toBeNull();
  });

  it("also shows multi-agent and scheduled-task settings once remote workspaces are enabled", () => {
    render(
      <SettingsModal
        isOpen
        isWebDeployment
        remoteWorkspacesEnabled
        onClose={vi.fn()}
        onModelChanged={vi.fn()}
        onImageModelChanged={vi.fn()}
      />,
    );

    expect(screen.getByText("Rôles multi-agent")).toBeInTheDocument();
    expect(screen.getByText("Modèles des rôles")).toBeInTheDocument();
    expect(screen.getByText("Serveurs MCP")).toBeInTheDocument();
    expect(screen.getByText("Tâches récurrentes")).toBeInTheDocument();
  });
});
