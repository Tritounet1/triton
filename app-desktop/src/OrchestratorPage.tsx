import { useEffect, useState } from "react";
import { Avatar } from "@astryxdesign/core/Avatar";
import {
  ChatComposer,
  ChatLayout,
  ChatMessage,
  ChatMessageBubble,
  ChatMessageMetadata,
  ChatMessageList,
  ChatToolCalls,
  type ChatToolCallStatus,
} from "@astryxdesign/core/Chat";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { ArrowLeftIcon, CpuIcon, PlusIcon } from "./icons";

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
  project_id: string | null;
}

interface ProjectOption {
  id: string;
  name: string;
}

function subtaskToCallStatus(status: SubtaskStatus): ChatToolCallStatus {
  return status === "done" ? "complete" : status;
}

interface OrchestratorPageProps {
  onBack: () => void;
}

/** Mode multi-agent : un planificateur decoupe une tache en sous-taches
 * taguees par role, chacune dispatchee sur le modele configure pour ce
 * role (voir model_roles.py). Rendu comme une conversation classique
 * (memes composants Chat que le mode normal) plutot qu'une liste de
 * cartes, mais reste un mode a part : ni les runs ni le project picker
 * ne touchent aux sessions/conversations normales - voir la decision
 * "fusionner Projets et multi-agent ?" dans PLAN.md. */
export function OrchestratorPage({ onBack }: OrchestratorPageProps) {
  const [runs, setRuns] = useState<OrchestratorRun[]>([]);
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [task, setTask] = useState("");
  const [dispatching, setDispatching] = useState(false);

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
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: ProjectOption[]) => {
        setProjects(data);
      })
      .catch(() => {
        // API hors ligne : le picker reste vide, le run part sans projet
      });
  }, []);

  useEffect(() => {
    loadRuns();
    const interval = setInterval(loadRuns, POLL_INTERVAL_MS);
    return () => {
      clearInterval(interval);
    };
  }, []);

  function dispatchTask(value: string) {
    const text = value.trim();
    if (!text || dispatching) return;
    setDispatching(true);
    fetch(`${API_BASE}/orchestrator`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task: text, project_id: selectedProjectId || null }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((data: { run_id: string } | null) => {
        setTask("");
        if (data) {
          setSelectedRunId(data.run_id);
          loadRuns();
        }
      })
      .catch(() => {
        // API hors ligne : rien de plus a afficher, l'utilisateur peut reessayer
      })
      .finally(() => {
        setDispatching(false);
      });
  }

  const selectedRun = runs.find((r) => r.id === selectedRunId) ?? null;
  const selectedRunProject = selectedRun?.project_id
    ? (projects.find((p) => p.id === selectedRun.project_id)?.name ?? null)
    : null;

  const runOptions = [
    { value: "", label: "Nouvelle tâche" },
    ...runs.map((r) => ({
      value: r.id,
      label: r.task.length > 40 ? `${r.task.slice(0, 40)}…` : r.task,
    })),
  ];

  const projectOptions = [
    { value: "", label: "Aucun projet" },
    ...projects.map((p) => ({ value: p.id, label: p.name })),
  ];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border px-6 py-4">
        <IconButton label="Retour" icon={<ArrowLeftIcon />} variant="ghost" size="sm" onClick={onBack} />
        <CpuIcon className="h-5 w-5 shrink-0 text-secondary" />
        <Text size="lg" weight="semibold">
          Mode multi-agent
        </Text>
        {selectedRunProject && (
          <Text size="2xs" color="secondary">
            · {selectedRunProject}
          </Text>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Selector
            label="Tâche"
            isLabelHidden
            options={runOptions}
            value={selectedRunId ?? ""}
            onChange={(v) => {
              setSelectedRunId(v || null);
            }}
            size="sm"
            width={220}
          />
          <IconButton
            label="Nouvelle tâche"
            icon={<PlusIcon />}
            variant="ghost"
            size="sm"
            onClick={() => {
              setSelectedRunId(null);
            }}
          />
        </div>
      </div>

      <ChatLayout
        density="spacious"
        className="h-full min-w-0 flex-1"
        emptyState={
          <EmptyState
            title="Nouvelle tâche multi-agent"
            description="Décris une tâche - un planificateur la répartit entre plusieurs agents spécialisés, chacun sur le modèle configuré pour son rôle."
          />
        }
        composer={
          <ChatComposer
            value={task}
            onChange={setTask}
            onSubmit={dispatchTask}
            isDisabled={dispatching}
            placeholder="Décris la tâche à répartir entre plusieurs agents..."
            density="compact"
            elevation="none"
            headerContext={
              <Selector
                label="Projet de travail"
                isLabelHidden
                options={projectOptions}
                value={selectedProjectId}
                onChange={setSelectedProjectId}
                size="sm"
                variant="ghost"
              />
            }
          />
        }
      >
        <ChatMessageList
          isStreaming={!!selectedRun && selectedRun.status !== "done" && selectedRun.status !== "error"}
        >
          {selectedRun && (
            <>
              <ChatMessage sender="user">
                <ChatMessageBubble
                  metadata={
                    <ChatMessageMetadata
                      timestamp={
                        <Timestamp
                          value={new Date(selectedRun.created_at).getTime() / 1000}
                          format="time"
                        />
                      }
                      status="sent"
                    />
                  }
                >
                  {selectedRun.task}
                </ChatMessageBubble>
              </ChatMessage>

              <ChatMessage
                sender="assistant"
                avatar={<Avatar name="Triton" size="sm" />}
                name="Triton"
              >
                {selectedRun.status === "planning" && (
                  <ChatToolCalls calls={[{ name: "planification", status: "running" }]} />
                )}

                {selectedRun.subtasks.length > 0 && (
                  <ChatToolCalls
                    calls={selectedRun.subtasks.map((s) => ({
                      key: s.id,
                      name: s.role,
                      status: subtaskToCallStatus(s.status),
                      target: s.model,
                      resultDetail: (
                        <div className="px-1 py-1">
                          <Text size="2xs" color="secondary" className="mb-1 block">
                            {s.description}
                          </Text>
                          {s.result && (
                            <Text size="sm" className="block whitespace-pre-wrap">
                              {s.result}
                            </Text>
                          )}
                        </div>
                      ),
                    }))}
                  />
                )}

                {selectedRun.error && (
                  <ChatMessageBubble variant="ghost" width="100%">
                    <span className="text-error">{selectedRun.error}</span>
                  </ChatMessageBubble>
                )}

                {selectedRun.final_result && (
                  <ChatMessageBubble variant="ghost" width="100%">
                    <Markdown>{selectedRun.final_result}</Markdown>
                  </ChatMessageBubble>
                )}
              </ChatMessage>
            </>
          )}
        </ChatMessageList>
      </ChatLayout>
    </div>
  );
}
