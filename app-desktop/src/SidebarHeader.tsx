import { Avatar } from "@astryxdesign/core/Avatar";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SideNavHeading } from "@astryxdesign/core/SideNav";
import { PlusIcon, SearchIcon, SidebarIcon } from "./icons";

interface SidebarHeaderProps {
  usesMacTitlebarOverlay: boolean;
  sidebarCollapsed: boolean;
  isWebDeployment: boolean;
  onToggleSidebar: () => void;
  onSearch: () => void;
  onNewConversation: () => void;
}

const SHORTCUT_PREFIX =
  typeof navigator !== "undefined" && navigator.userAgent.includes("Mac") ? "⌘" : "Ctrl ";

export function SidebarHeader({
  usesMacTitlebarOverlay,
  sidebarCollapsed,
  isWebDeployment,
  onToggleSidebar,
  onSearch,
  onNewConversation,
}: SidebarHeaderProps) {
  return {
    header: (
      <SideNavHeading
        heading="Triton"
        subheading={isWebDeployment ? "Instance web" : "Application locale"}
        icon={<Avatar src="/default-logo.png" name="Triton" size="lg" />}
        headerEndContent={
          !usesMacTitlebarOverlay && (
            <IconButton
              label={sidebarCollapsed ? "Épingler ouverte" : "Fermer la barre latérale"}
              icon={<SidebarIcon />}
              variant="ghost"
              size="sm"
              onClick={onToggleSidebar}
            />
          )
        }
      />
    ),
    topContent: (
      <div className="flex flex-col gap-1">
        <button
          type="button"
          onClick={onNewConversation}
          className="flex h-10 w-full items-center gap-2.5 rounded-[10px] bg-accent-bg px-3 text-sm font-medium text-on-accent transition-opacity hover:opacity-90 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
        >
          <PlusIcon className="h-4 w-4" />
          <span className="flex-1 text-left">Nouvelle conversation</span>
          <kbd className="triton-kbd border-none">{SHORTCUT_PREFIX}N</kbd>
        </button>
        <button
          type="button"
          onClick={onSearch}
          className="flex h-9 w-full items-center gap-2.5 rounded-lg px-3 text-sm text-primary transition-colors hover:bg-overlay-hover focus-visible:outline-2 focus-visible:outline-brand"
        >
          <SearchIcon className="h-4 w-4 text-secondary" />
          <span className="flex-1 text-left">Rechercher</span>
          <kbd className="triton-kbd border-none text-secondary">{SHORTCUT_PREFIX}K</kbd>
        </button>
      </div>
    ),
  };
}
