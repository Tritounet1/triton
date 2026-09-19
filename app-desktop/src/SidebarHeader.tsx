import { Avatar } from "@astryxdesign/core/Avatar";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { SideNavHeading } from "@astryxdesign/core/SideNav";
import { PlusIcon, SearchIcon, SidebarIcon } from "./icons";

interface SidebarHeaderProps {
  usesMacTitlebarOverlay: boolean;
  sidebarCollapsed: boolean;
  onToggleSidebar: () => void;
  onSearch: () => void;
  onNewConversation: () => void;
}

export function SidebarHeader({
  usesMacTitlebarOverlay,
  sidebarCollapsed,
  onToggleSidebar,
  onSearch,
  onNewConversation,
}: SidebarHeaderProps) {
  return {
    header: (
      <SideNavHeading
        heading="Triton"
        icon={<Avatar src="/default-logo.png" name="Triton" size="lg" />}
        headerEndContent={
          <div className="flex items-center gap-0.5">
            {!usesMacTitlebarOverlay && (
              <IconButton
                label={sidebarCollapsed ? "Épingler ouverte" : "Fermer la barre latérale"}
                icon={<SidebarIcon />}
                variant="ghost"
                size="sm"
                onClick={onToggleSidebar}
              />
            )}
            <IconButton label="Rechercher" icon={<SearchIcon />} variant="ghost" size="sm" onClick={onSearch} />
          </div>
        }
      />
    ),
    topContent: (
      <Button
        label="Nouvelle conversation"
        icon={<PlusIcon />}
        variant="secondary"
        size="sm"
        onClick={onNewConversation}
        className="w-full justify-start"
      />
    ),
  };
}
