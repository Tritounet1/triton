import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ChatHeader } from "./ChatHeader";

function renderHeader(overrides: Partial<Parameters<typeof ChatHeader>[0]> = {}) {
  const onTogglePanel = vi.fn();
  render(
    <ChatHeader
      projectName="api-billing"
      title="Validation de l'export"
      status="idle"
      model="z-ai/glm-5.3-flash"
      yoloEnabled={false}
      isPanelOpen
      onTogglePanel={onTogglePanel}
      {...overrides}
    />,
  );
  return { onTogglePanel };
}

describe("ChatHeader", () => {
  it("shows the project breadcrumb, title and model", () => {
    renderHeader();
    expect(screen.getByText("api-billing")).toBeInTheDocument();
    expect(screen.getByText("Validation de l'export")).toBeInTheDocument();
    expect(screen.getByText("z-ai/glm-5.3-flash")).toBeInTheDocument();
    expect(screen.queryByText("Agent en cours")).toBeNull();
    expect(screen.queryByText("Attend ton accord")).toBeNull();
  });

  it("announces a running agent and a pending approval", () => {
    const { unmount } = render(
      <ChatHeader
        projectName={null}
        title="Conversation"
        status="running"
        model={null}
        yoloEnabled={false}
        isPanelOpen={false}
        onTogglePanel={vi.fn()}
      />,
    );
    expect(screen.getByText("Agent en cours")).toBeInTheDocument();
    unmount();
    renderHeader({ status: "awaiting", yoloEnabled: true });
    expect(screen.getByText("Attend ton accord")).toBeInTheDocument();
    expect(screen.getByText("YOLO")).toBeInTheDocument();
  });

  it("toggles the side panel", async () => {
    const user = userEvent.setup();
    const { onTogglePanel } = renderHeader();
    await user.click(screen.getByRole("button", { name: "Masquer le panneau" }));
    expect(onTogglePanel).toHaveBeenCalledOnce();
  });
});
