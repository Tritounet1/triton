import { IconButton } from "@astryxdesign/core/IconButton";
import { ChevronRightIcon, PanelRightIcon } from "./icons";
import { ProjectTile } from "./ProjectTile";

export type AgentStatus = "idle" | "running" | "awaiting";

interface ChatHeaderProps {
  projectName: string | null;
  title: string;
  status: AgentStatus;
  model: string | null;
  yoloEnabled: boolean;
  isPanelOpen: boolean;
  onTogglePanel: () => void;
}

const STATUS_LABEL: Record<Exclude<AgentStatus, "idle">, string> = {
  running: "Agent en cours",
  awaiting: "Attend ton accord",
};

export function ChatHeader({
  projectName,
  title,
  status,
  model,
  yoloEnabled,
  isPanelOpen,
  onTogglePanel,
}: ChatHeaderProps) {
  return (
    <header className="flex min-h-14 shrink-0 flex-wrap items-center gap-3 border-b border-line px-5 py-2.5">
      <nav aria-label="Fil d’Ariane" className="flex min-w-0 flex-1 items-center gap-2 text-sm">
        {projectName && (
          <>
            <span className="flex shrink-0 items-center gap-2 text-secondary">
              <ProjectTile name={projectName} />
              {projectName}
            </span>
            <ChevronRightIcon className="h-3.5 w-3.5 shrink-0 text-disabled" />
          </>
        )}
        <span className="truncate font-semibold text-primary">{title}</span>
        {status !== "idle" && (
          <span
            role="status"
            className={`ml-1 inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
              status === "awaiting" ? "bg-warn-icon text-warn-text" : "bg-brand-muted text-brand-text"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                status === "awaiting" ? "bg-warn-text" : "animate-pulse bg-brand"
              }`}
            />
            {STATUS_LABEL[status]}
          </span>
        )}
        {yoloEnabled && (
          <span className="inline-flex shrink-0 items-center rounded-full bg-warn-icon px-2.5 py-0.5 text-xs font-medium text-warn-text">
            YOLO
          </span>
        )}
      </nav>
      <div className="flex items-center gap-2">
        {model && (
          <span className="hidden max-w-56 truncate rounded-md border border-line px-2 py-1 font-mono text-xs text-secondary sm:inline">
            {model}
          </span>
        )}
        <IconButton
          label={isPanelOpen ? "Masquer le panneau" : "Afficher le panneau"}
          icon={<PanelRightIcon />}
          variant={isPanelOpen ? "secondary" : "ghost"}
          size="sm"
          onClick={onTogglePanel}
        />
      </div>
    </header>
  );
}
