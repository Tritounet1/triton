import { useEffect, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { ArrowLeftIcon, ChevronRightIcon, CpuIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 2000;

type RunStatus = "planning" | "running" | "done" | "error";
type SubtaskStatus = "pending" | "running" | "done" | "error";

interface OrchestratorSubtask {
  id: string;
  role: string;
  description: string;
  model: string;
  status: SubtaskStatus;
  result: string | null;
}

interface OrchestratorRun {
  id: string;
  task: string;
  status: RunStatus;
  subtasks: OrchestratorSubtask[];
  final_result: string | null;
  error: string | null;
  created_at: string;
}

function runStatusVariant(status: RunStatus): "success" | "error" | "warning" {
  if (status === "done") return "success";
  if (status === "error") return "error";
  return "warning"; // planning / running
}

function runStatusLabel(status: RunStatus): string {
  if (status === "planning") return "planification";
  if (status === "running") return "en cours";
  if (status === "error") return "erreur";
  return "terminé";
}

function subtaskStatusVariant(status: SubtaskStatus): "success" | "error" | "warning" | "neutral" {
  if (status === "done") return "success";
  if (status === "error") return "error";
  if (status === "running") return "warning";
  return "neutral";
}

interface OrchestratorPageProps {
  onBack: () => void;
}

/** Mode multi-agent : un planificateur decoupe une tache en sous-taches
 * taguees par role, chacune dispatchee sur le modele configure pour ce
 * role (voir model_roles.py), puis synthetise les resultats. Entierement
 * separe du chat/des projets - orchestrator.py ne touche ni aux sessions
 * ni aux fichiers. */
export function OrchestratorPage({ onBack }: OrchestratorPageProps) {
  const [runs, setRuns] = useState<OrchestratorRun[]>([]);
  const [task, setTask] = useState("");
  const [dispatching, setDispatching] = useState(false);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  function loadRuns() {
    fetch(`${API_BASE}/orchestrator`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: OrchestratorRun[]) => {
        setRuns(data);
      })
      .catch(() => {
        // API hors ligne : la liste reste telle quelle
      });
  }

  useEffect(() => {
    loadRuns();
    const interval = setInterval(loadRuns, POLL_INTERVAL_MS);
    return () => {
      clearInterval(interval);
    };
  }, []);

  function dispatchTask() {
    const value = task.trim();
    if (!value || dispatching) return;
    setDispatching(true);
    fetch(`${API_BASE}/orchestrator`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: value }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { run_id: string } | null) => {
        setTask("");
        if (data) setExpandedRunId(data.run_id);
        loadRuns();
      })
      .catch(() => {
        // API hors ligne : rien a afficher de plus, l'utilisateur peut reessayer
      })
      .finally(() => {
        setDispatching(false);
      });
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <IconButton label="Retour" icon={<ArrowLeftIcon />} variant="ghost" size="sm" onClick={onBack} />
        <div className="flex items-center gap-2">
          <CpuIcon className="h-5 w-5 text-secondary" />
          <Text size="lg" weight="semibold">
            Mode multi-agent
          </Text>
        </div>
      </div>

      <div className="mb-8 flex flex-col gap-3 rounded-xl border border-border p-4">
        <TextArea
          label="Tâche à répartir entre plusieurs agents"
          isLabelHidden
          value={task}
          onChange={setTask}
          placeholder="Décris la tâche - un planificateur la découpe en sous-tâches et les répartit entre plusieurs agents..."
          rows={3}
          isDisabled={dispatching}
        />
        <Button
          label="Lancer"
          variant="primary"
          size="sm"
          isDisabled={!task.trim() || dispatching}
          isLoading={dispatching}
          onClick={dispatchTask}
          className="self-end"
        >
          Lancer
        </Button>
      </div>

      {runs.length === 0 ? (
        <EmptyState
          title="Aucune tâche encore"
          description="Lance une première tâche pour voir le planificateur la répartir entre plusieurs agents."
        />
      ) : (
        <div className="flex flex-col gap-2">
          {runs.map((run) => {
            const isExpanded = expandedRunId === run.id;
            return (
              <div key={run.id} className="overflow-hidden rounded-xl border border-border">
                <button
                  onClick={() => {
                    setExpandedRunId(isExpanded ? null : run.id);
                  }}
                  className="flex w-full items-center gap-3 bg-surface px-4 py-3 text-left hover:bg-muted"
                >
                  <Text weight="medium" className="min-w-0 flex-1 truncate">
                    {run.task}
                  </Text>
                  <Badge variant={runStatusVariant(run.status)} label={runStatusLabel(run.status)} />
                  <ChevronRightIcon
                    className={`h-4 w-4 shrink-0 text-secondary transition-transform ${isExpanded ? "rotate-90" : ""}`}
                  />
                </button>
                {isExpanded && (
                  <div className="flex flex-col gap-4 border-t border-border px-4 py-4">
                    {run.error && (
                      <Text size="sm" className="block text-error">
                        {run.error}
                      </Text>
                    )}
                    {run.subtasks.length > 0 && (
                      <div className="flex flex-col gap-2">
                        {run.subtasks.map((s) => (
                          <div key={s.id} className="rounded-lg border border-border p-3">
                            <div className="mb-1 flex flex-wrap items-center gap-2">
                              <Badge variant="neutral" label={s.role} />
                              <Text size="2xs" color="secondary">
                                {s.model}
                              </Text>
                              <Badge variant={subtaskStatusVariant(s.status)} label={s.status} />
                            </div>
                            <Text size="sm" color="secondary" className="block">
                              {s.description}
                            </Text>
                            {s.result && (
                              <Text size="sm" className="mt-2 block whitespace-pre-wrap">
                                {s.result}
                              </Text>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                    {run.final_result && (
                      <div className="rounded-lg bg-muted p-3">
                        <Text
                          size="2xs"
                          weight="semibold"
                          color="secondary"
                          className="mb-1 block uppercase"
                        >
                          Synthèse
                        </Text>
                        <Text size="sm" className="block whitespace-pre-wrap">
                          {run.final_result}
                        </Text>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
