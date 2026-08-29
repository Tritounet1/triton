import { BackgroundTasksSection, type BackgroundTask } from "./BackgroundTasksSection";

interface BackgroundTasksPanelProps {
  tasks: BackgroundTask[];
  onOpen: (id: string) => void;
  onStop: (id: string) => void;
  onDelete: (id: string) => void;
}

/** Panneau lateral droit pour une conversation sans projet actif : n'affiche
 * rien tant qu'aucune tache n'a ete lancee (contrairement a ProjectFilePanel,
 * qui integre la meme section au-dessus de son arbre de fichiers). */
export function BackgroundTasksPanel({ tasks, onOpen, onStop, onDelete }: BackgroundTasksPanelProps) {
  if (tasks.length === 0) return null;

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-border">
      <BackgroundTasksSection tasks={tasks} onOpen={onOpen} onStop={onStop} onDelete={onDelete} />
    </div>
  );
}
