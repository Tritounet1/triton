import { useEffect, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Switch } from "@astryxdesign/core/Switch";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { PlusIcon, TrashIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

type Frequency = "hourly" | "daily" | "weekly";

interface ScheduledTask {
  id: string;
  prompt: string;
  frequency: Frequency;
  time_of_day: string;
  project_id: string;
  session_id: string;
  day_of_week: number | null;
  enabled: boolean;
  next_run: string;
  last_run: string | null;
}

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

const DAY_LABELS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

const TIME_PATTERN = /^([01]\d|2[0-3]):([0-5]\d)$/;

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" });
}

/** Resume lisible de la frequence d'une tache - l'heure n'a de sens que
 * pour daily/weekly (voir compute_next_run cote serveur : la partie heure
 * de time_of_day est ignoree pour hourly, seule la minute compte). */
function describeSchedule(task: ScheduledTask): string {
  if (task.frequency === "hourly") {
    const minute = task.time_of_day.split(":")[1] ?? "00";
    return `Toutes les heures, à :${minute}`;
  }
  if (task.frequency === "daily") {
    return `Tous les jours à ${task.time_of_day}`;
  }
  const day = task.day_of_week !== null ? DAY_LABELS[task.day_of_week] : "?";
  return `Tous les ${day}s à ${task.time_of_day}`;
}

/** Meme convention que McpSettings.tsx (formulaire pliable, liste, une
 * seule AlertDialog de confirmation pour la suppression) - voir sa propre
 * description pour le principe general des panneaux de Reglages. */
export function ScheduledTasksSettings() {
  const [tasks, setTasks] = useState<ScheduledTask[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const [prompt, setPrompt] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [timeOfDay, setTimeOfDay] = useState("09:00");
  const [dayOfWeek, setDayOfWeek] = useState(0);
  const [projectId, setProjectId] = useState("");

  // pas d'appel synchrone a setLoading() ici (seulement dans les callbacks) :
  // meme garde-fou que McpSettings.tsx (react-hooks set-state-in-effect).
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/scheduled_tasks`).then((r) => (r.ok ? r.json() : [])),
      fetch(`${API_BASE}/projects`).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([taskData, projectData]: [ScheduledTask[], Project[]]) => {
        setTasks(taskData);
        setProjects(projectData);
        setProjectId((current) => current || (projectData[0]?.id ?? ""));
      })
      .catch(() => {
        setTasks([]);
        setProjects([]);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  function resetForm() {
    setPrompt("");
    setFrequency("daily");
    setTimeOfDay("09:00");
    setDayOfWeek(0);
    setFormError(null);
    setShowForm(false);
  }

  async function submitForm() {
    if (!prompt.trim()) {
      setFormError("le prompt est obligatoire.");
      return;
    }
    if (!projectId) {
      setFormError("choisis un projet.");
      return;
    }
    if (!TIME_PATTERN.test(timeOfDay)) {
      setFormError("l'heure doit être au format HH:MM (ex. 09:00).");
      return;
    }
    setSubmitting(true);
    setFormError(null);

    try {
      const res = await fetch(`${API_BASE}/scheduled_tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: prompt.trim(),
          frequency,
          time_of_day: timeOfDay,
          project_id: projectId,
          day_of_week: frequency === "weekly" ? dayOfWeek : null,
        }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setFormError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      const created = (await res.json()) as ScheduledTask;
      setTasks((prev) => [...prev, created]);
      resetForm();
    } catch {
      setFormError("impossible de contacter l'API Triton (127.0.0.1:8000).");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleTask(task: ScheduledTask) {
    const res = await fetch(`${API_BASE}/scheduled_tasks/${task.id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !task.enabled }),
    });
    if (!res.ok) return;
    const updated = (await res.json()) as ScheduledTask;
    setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
  }

  async function confirmDelete() {
    if (!deletingId) return;
    const id = deletingId;
    const res = await fetch(`${API_BASE}/scheduled_tasks/${id}`, { method: "DELETE" });
    setDeletingId(null);
    if (res.ok) setTasks((prev) => prev.filter((t) => t.id !== id));
  }

  const deletingTask = tasks.find((t) => t.id === deletingId);

  return (
    <div>
      <div className="mb-4 flex items-center justify-between gap-3">
        <Text size="lg" weight="semibold">
          Tâches récurrentes
        </Text>
        <Button
          label="Ajouter une tâche"
          icon={<PlusIcon />}
          variant="secondary"
          size="sm"
          isDisabled={projects.length === 0}
          onClick={() => {
            setShowForm((v) => !v);
          }}
        />
      </div>

      <Text size="sm" color="secondary" className="mb-6 block">
        Un prompt qui se relance tout seul selon une fréquence, envoyé dans sa propre
        conversation dédiée (son historique s'accumule à chaque déclenchement). Vérifié
        uniquement quand l'app tourne - pas de rattrapage si elle est restée fermée : une
        échéance manquée est simplement sautée, la prochaine est recalculée à partir de
        maintenant. Les demandes d'autorisation (écriture, commande...) sont automatiquement
        sautées à chaque déclenchement, comme le mode{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">/yolo</code> : personne n'est là
        pour les valider.
      </Text>

      {!loading && projects.length === 0 && (
        <Text size="sm" className="mb-4 block text-error">
          Crée d'abord un projet - une tâche récurrente a besoin d'un projet cible.
        </Text>
      )}

      {showForm && (
        <div className="mb-6 rounded-xl border border-border bg-surface p-4">
          <TextArea
            label="Prompt"
            value={prompt}
            onChange={setPrompt}
            rows={3}
            placeholder="Résume les fichiers modifiés aujourd'hui dans ce projet."
            className="mb-3"
          />
          <div className="mb-3 grid grid-cols-2 gap-3">
            <div>
              <Text size="sm" className="mb-1 block">
                Projet
              </Text>
              <select
                className="w-full rounded-md border border-border bg-transparent p-2 text-sm"
                value={projectId}
                onChange={(e) => {
                  setProjectId(e.target.value);
                }}
              >
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <Text size="sm" className="mb-1 block">
                Fréquence
              </Text>
              <select
                className="w-full rounded-md border border-border bg-transparent p-2 text-sm"
                value={frequency}
                onChange={(e) => {
                  setFrequency(e.target.value as Frequency);
                }}
              >
                <option value="hourly">Toutes les heures</option>
                <option value="daily">Tous les jours</option>
                <option value="weekly">Toutes les semaines</option>
              </select>
            </div>
          </div>
          <div className="mb-3 grid grid-cols-2 gap-3">
            <TextInput
              label={frequency === "hourly" ? "Minute (à chaque heure, HH ignoré)" : "Heure"}
              value={timeOfDay}
              onChange={setTimeOfDay}
              placeholder="09:00"
              size="sm"
            />
            {frequency === "weekly" && (
              <div>
                <Text size="sm" className="mb-1 block">
                  Jour
                </Text>
                <select
                  className="w-full rounded-md border border-border bg-transparent p-2 text-sm"
                  value={dayOfWeek}
                  onChange={(e) => {
                    setDayOfWeek(Number(e.target.value));
                  }}
                >
                  {DAY_LABELS.map((label, i) => (
                    <option key={label} value={i}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
          {formError && (
            <Text size="sm" className="mb-3 block text-error">
              {formError}
            </Text>
          )}
          <div className="flex gap-2">
            <Button
              label="Créer"
              variant="primary"
              size="sm"
              isLoading={submitting}
              onClick={() => {
                void submitForm();
              }}
            >
              Créer
            </Button>
            <Button label="Annuler" variant="ghost" size="sm" onClick={resetForm}>
              Annuler
            </Button>
          </div>
        </div>
      )}

      {!loading && tasks.length === 0 && !showForm ? (
        <EmptyState
          title="Aucune tâche récurrente"
          description="Programme un prompt qui se relance tout seul, au lieu de le retaper à chaque fois."
        />
      ) : (
        <div className="space-y-2">
          {tasks.map((t) => {
            const project = projects.find((p) => p.id === t.project_id);
            return (
              <div key={t.id} className="rounded-xl border border-border bg-surface p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Text weight="semibold" className="block truncate">
                        {t.prompt}
                      </Text>
                      {!t.enabled && <Badge variant="neutral" label="désactivée" />}
                    </div>
                    <Text size="2xs" color="secondary" className="mt-1 block">
                      {describeSchedule(t)} · {project?.name ?? t.project_id}
                    </Text>
                    <Text size="2xs" color="secondary" className="mt-1 block">
                      Prochaine échéance : {formatDateTime(t.next_run)}
                      {t.last_run && ` · dernière exécution : ${formatDateTime(t.last_run)}`}
                    </Text>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      label="Activée"
                      isLabelHidden
                      value={t.enabled}
                      onChange={() => {
                        void toggleTask(t);
                      }}
                      size="sm"
                    />
                    <IconButton
                      label="Supprimer"
                      icon={<TrashIcon />}
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setDeletingId(t.id);
                      }}
                    />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      <AlertDialog
        isOpen={deletingId !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingId(null);
        }}
        title="Supprimer cette tâche récurrente ?"
        description={`« ${deletingTask?.prompt ?? ""} » ne se relancera plus. Sa conversation et son historique restent conservés.`}
        actionLabel="Supprimer"
        onAction={confirmDelete}
      />
    </div>
  );
}
