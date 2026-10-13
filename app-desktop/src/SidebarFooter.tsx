import { IconButton } from "@astryxdesign/core/IconButton";
import { GearIcon, MoonIcon, SunIcon } from "./icons";

interface SidebarFooterProps {
  isWebDeployment: boolean;
  themeMode: "light" | "dark";
  onOpenSettings: () => void;
  onToggleTheme: () => void;
}

export function SidebarFooter({
  isWebDeployment,
  themeMode,
  onOpenSettings,
  onToggleTheme,
}: SidebarFooterProps) {
  const host = isWebDeployment && typeof window !== "undefined" ? window.location.host : "";
  const title = isWebDeployment ? "Instance web" : "Triton Desktop";
  const subtitle = isWebDeployment ? host : "Workspace local";

  return (
    <div className="flex items-center gap-2.5 rounded-xl border border-line bg-surface p-2.5">
      <span
        aria-hidden="true"
        className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand-muted text-[13px] font-semibold text-brand-text"
      >
        {isWebDeployment ? (host.charAt(0).toUpperCase() || "W") : "T"}
      </span>
      <div className="flex min-w-0 flex-1 flex-col leading-tight">
        <span className="truncate text-[13px] font-medium text-primary">{title}</span>
        <span className="truncate text-xs text-secondary">{subtitle}</span>
      </div>
      <IconButton
        label={themeMode === "dark" ? "Passer en thème clair" : "Passer en thème sombre"}
        icon={themeMode === "dark" ? <MoonIcon /> : <SunIcon />}
        variant="ghost"
        size="sm"
        onClick={onToggleTheme}
      />
      <IconButton
        label="Paramètres"
        icon={<GearIcon />}
        variant="ghost"
        size="sm"
        onClick={onOpenSettings}
      />
    </div>
  );
}
