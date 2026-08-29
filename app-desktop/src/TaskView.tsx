import { useCallback, useEffect, useRef, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { ArrowLeftIcon, StopIcon, TerminalIcon } from "./icons";
import type { BackgroundTask } from "./BackgroundTasksSection";

const API_BASE = "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 1500;

interface TaskDetail extends BackgroundTask {
  logs: string;
}

function statusVariant(status: TaskDetail["status"]): "success" | "error" | "neutral" | "warning" {
  if (status === "running") return "success";
  if (status === "error") return "error";
  if (status === "stopped") return "neutral";
  return "warning";
}

function statusLabel(status: TaskDetail["status"]): string {
  if (status === "running") return "en cours";
  if (status === "error") return "erreur";
  if (status === "stopped") return "arrêtée";
  return "terminée";
}

interface TaskViewProps {
  taskId: string;
  onBack: () => void;
}

/** Vue plein ecran style terminal pour une tache en arriere-plan
 * (start_background_task) : suivi en direct de sa sortie par polling (pas
 * de flux SSE dedie, cf. l'approche deja retenue pour les sous-agents dans
 * SubagentsPanel.tsx), avec un bouton pour l'arreter. */
export function TaskView({ taskId, onBack }: TaskViewProps) {
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [notFound, setNotFound] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);

  const loadTask = useCallback(() => {
    fetch(`${API_BASE}/background_tasks/${taskId}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: TaskDetail) => { setTask(data); })
      .catch(() => { setNotFound(true); });
  }, [taskId]);

  useEffect(() => {
    loadTask();
    const interval = setInterval(loadTask, POLL_INTERVAL_MS);
    return () => { clearInterval(interval); };
  }, [loadTask]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [task?.logs]);

  function stopTask() {
    fetch(`${API_BASE}/background_tasks/${taskId}/stop`, { method: "POST" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: TaskDetail | null) => { if (data) setTask(data); })
      .catch(() => {
        // API hors ligne : le prochain polling reflete quand meme l'etat reel
      });
  }

  return (
    <div className="flex h-full flex-col px-6 py-6">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <IconButton
            label="Retour"
            icon={<ArrowLeftIcon />}
            variant="ghost"
            size="sm"
            onClick={onBack}
          />
          <TerminalIcon className="h-5 w-5 shrink-0 text-secondary" />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Text size="lg" weight="semibold" className="truncate">
                {task?.name ?? taskId}
              </Text>
              {task && <Badge variant={statusVariant(task.status)} label={statusLabel(task.status)} />}
            </div>
            {task && (
              <Text size="2xs" color="secondary" className="block truncate">
                {task.command} · {task.directory}
              </Text>
            )}
          </div>
        </div>
        {task?.status === "running" && (
          <Button
            label="Arrêter"
            variant="secondary"
            size="sm"
            icon={<StopIcon className="h-4 w-4" />}
            onClick={stopTask}
          />
        )}
      </div>

      {notFound ? (
        <Text size="sm" color="secondary">
          Cette tâche n'existe plus (le serveur a peut-être redémarré).
        </Text>
      ) : (
        <div
          ref={logRef}
          className="min-h-0 flex-1 overflow-y-auto whitespace-pre-wrap rounded-lg bg-[#111318] p-4 font-mono text-xs text-[#d4d4d4]"
        >
          {task && task.logs.length > 0 ? task.logs : "(pas encore de sortie)"}
        </div>
      )}
    </div>
  );
}
