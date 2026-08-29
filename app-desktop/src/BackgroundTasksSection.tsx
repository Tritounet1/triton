import { Badge } from "@astryxdesign/core/Badge";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { StopIcon, TerminalIcon } from "./icons";

export interface BackgroundTask {
  id: string;
  session_id: string;
  name: string;
  command: string;
  directory: string;
  status: "running" | "exited" | "error" | "stopped";
  exit_code: number | null;
  created_at: string;
}

function statusVariant(status: BackgroundTask["status"]): "success" | "error" | "neutral" | "warning" {
  if (status === "running") return "success";
  if (status === "error") return "error";
  if (status === "stopped") return "neutral";
  return "warning";
}

function statusLabel(status: BackgroundTask["status"]): string {
  if (status === "running") return "en cours";
  if (status === "error") return "erreur";
  if (status === "stopped") return "arrêtée";
  return "terminée";
}

interface BackgroundTasksSectionProps {
  tasks: BackgroundTask[];
  onOpen: (id: string) => void;
  onStop: (id: string) => void;
}

/** Taches lancees par le modele (start_background_task, ex. un serveur de
 * dev) : affichees dans le panneau lateral droit de la conversation, un
 * clic ouvre la vue terminal plein ecran (voir TaskView.tsx). */
export function BackgroundTasksSection({ tasks, onOpen, onStop }: BackgroundTasksSectionProps) {
  if (tasks.length === 0) return null;

  return (
    <div className="border-b border-border px-2 py-2">
      <Text size="2xs" weight="semibold" color="secondary" className="block px-2 pb-1 uppercase">
        Tâches en arrière-plan
      </Text>
      {tasks.map((t) => (
        <div
          key={t.id}
          className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 hover:bg-muted"
          onClick={() => { onOpen(t.id); }}
        >
          <TerminalIcon className="h-4 w-4 shrink-0 text-secondary" />
          <Text size="sm" className="min-w-0 flex-1 truncate">
            {t.name}
          </Text>
          <Badge variant={statusVariant(t.status)} label={statusLabel(t.status)} />
          {t.status === "running" && (
            <IconButton
              label="Arrêter"
              icon={<StopIcon />}
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                onStop(t.id);
              }}
            />
          )}
        </div>
      ))}
    </div>
  );
}
