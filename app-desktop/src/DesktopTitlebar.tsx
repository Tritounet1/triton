import { IconButton } from "@astryxdesign/core/IconButton";
import { SidebarIcon } from "./icons";

interface DesktopTitlebarProps {
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
}

/** macOS traffic-light companion bar. The drag region must stay in its own component. */
export function DesktopTitlebar({ sidebarCollapsed, onToggleSidebar }: DesktopTitlebarProps) {
  return (
    <div className="flex h-[44px] shrink-0 items-center border-b border-border bg-surface pl-[84px]">
      <IconButton
        label={sidebarCollapsed ? "Afficher la barre latérale" : "Masquer la barre latérale"}
        icon={<SidebarIcon />}
        variant="ghost"
        size="sm"
        onClick={onToggleSidebar}
      />
      <div data-tauri-drag-region className="h-full flex-1" />
    </div>
  );
}
