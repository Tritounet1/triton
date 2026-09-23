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
import { Selector } from "@astryxdesign/core/Selector";
import { ClockIcon, PlusIcon, TrashIcon } from "./icons";

import { API_BASE } from "./api";

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
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  const [prompt, setPrompt] = useState("");
  const [frequency, setFrequency] = useState<Frequency>("daily");
  const [timeOfDay, setTimeOfDay] = useState("09:00");
  const [dayOfWeek, setDayOfWeek] = useState(0);
  const [projectId, setProjectId] = useState("");

  // no synchronous setLoading() call here (only inside callbacks): same
  // guard as McpSettings.tsx (react-hooks set-state-in-effect).
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
        setError("Impossible de charger les tâches récurrentes.");
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
    setUpdatingId(task.id);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/scheduled_tasks/${task.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !task.enabled }),
      });
      if (!res.ok) throw new Error("scheduled task update failed");
      const updated = (await res.json()) as ScheduledTask;
      setTasks((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
    } catch {
      setError("Impossible de modifier cette tâche.");
    } finally {
      setUpdatingId(null);
    }
  }

  async function confirmDelete() {
    if (!deletingId) return;
    const id = deletingId;
    setDeletingId(null);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/scheduled_tasks/${id}`, { method: "DELETE" });
      if (!res.ok) throw new Error("scheduled task deletion failed");
      setTasks((prev) => prev.filter((t) => t.id !== id));
    } catch {
      setError("Impossible de supprimer cette tâche.");
    }
  }

  const deletingTask = tasks.find((t) => t.id === deletingId);

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-4 pr-8">
        <div>
          <Text size="lg" weight="semibold" className="mb-1 block">
            Tâches récurrentes
          </Text>
          <Text size="sm" color="secondary" className="block max-w-xl">
            Planifie des prompts qui se relancent automatiquement dans leur propre conversation.
          </Text>
        </div>
        {!loading && tasks.length > 0 && (
          <Badge
            variant="blue"
            label={`${tasks.length} tâche${tasks.length > 1 ? "s" : ""}`}
            className="shrink-0"
          />
        )}
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-xl bg-accent-muted px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 text-accent">
            <ClockIcon className="h-4 w-4" />
          </div>
          <Text size="2xs" color="secondary">
            Elles ne s'exécutent que lorsque l'application est ouverte. Les demandes
            d'autorisation sont automatiquement acceptées, comme avec <code>/yolo</code>.
          </Text>
        </div>
        {!showForm && (
          <Button
            label="Ajouter une tâche"
            icon={<PlusIcon />}
            variant="primary"
            size="sm"
            className="shrink-0"
            isDisabled={projects.length === 0}
            onClick={() => { setShowForm(true); }}
          />
        )}
      </div>

      {!loading && projects.length === 0 && (
        <Text size="sm" className="mb-4 block rounded-xl bg-error-muted px-3 py-3 text-error">
          Crée d'abord un projet - une tâche récurrente a besoin d'un projet cible.
        </Text>
      )}

      {showForm && (
        <section className="mb-4 overflow-hidden rounded-2xl border border-accent bg-surface">
          <div className="flex items-center gap-3 border-b border-border bg-accent-muted px-4 py-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface text-accent">
              <PlusIcon className="h-5 w-5" />
            </div>
            <div>
              <Text weight="semibold" className="block">Nouvelle tâche récurrente</Text>
              <Text size="2xs" color="secondary" className="block">
                Le prompt recevra son propre historique à chaque déclenchement.
              </Text>
            </div>
          </div>
          <div className="p-4">
            <TextArea
              label="Prompt"
              value={prompt}
              onChange={setPrompt}
              rows={3}
              placeholder="Résume les fichiers modifiés aujourd'hui dans ce projet."
              className="mb-3"
            />
            <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <Selector
                label="Projet"
                options={projects.map((project) => ({ value: project.id, label: project.name }))}
                value={projectId}
                onChange={(value) => { if (value) setProjectId(value); }}
                size="sm"
              />
              <Selector
                label="Fréquence"
                options={[
                  { value: "hourly", label: "Toutes les heures" },
                  { value: "daily", label: "Tous les jours" },
                  { value: "weekly", label: "Toutes les semaines" },
                ]}
                value={frequency}
                onChange={(value) => { if (value) setFrequency(value as Frequency); }}
                size="sm"
              />
            </div>
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
              <TextInput
                label={frequency === "hourly" ? "Minute (HH ignoré)" : "Heure"}
                value={timeOfDay}
                onChange={setTimeOfDay}
                placeholder="09:00"
                size="sm"
              />
              {frequency === "weekly" && (
                <Selector
                  label="Jour"
                  options={DAY_LABELS.map((label, index) => ({ value: String(index), label }))}
                  value={String(dayOfWeek)}
                  onChange={(value) => { setDayOfWeek(Number(value)); }}
                  size="sm"
                />
              )}
            </div>
            {formError && <Text size="sm" className="mb-3 block text-error">{formError}</Text>}
            <div className="flex items-center gap-2">
              <Button
                label="Créer la tâche"
                icon={<ClockIcon />}
                variant="primary"
                size="sm"
                isLoading={submitting}
                onClick={() => { void submitForm(); }}
              />
              <Button label="Annuler" variant="ghost" size="sm" onClick={resetForm} />
            </div>
          </div>
        </section>
      )}

      {error && <Text size="sm" className="mb-3 block text-error">{error}</Text>}

      {loading && (
        <div className="flex flex-col gap-3" role="status" aria-label="Chargement des tâches">
          {[0, 1, 2].map((item) => (
            <div key={item} className="h-28 animate-pulse rounded-2xl border border-border bg-muted" />
          ))}
        </div>
      )}

      {!loading && tasks.length === 0 && !showForm && !error ? (
        <EmptyState
          title="Aucune tâche récurrente"
          description="Programme un prompt qui se relance tout seul, au lieu de le retaper à chaque fois."
        />
      ) : !loading && tasks.length > 0 ? (
        <div className="flex flex-col gap-3">
          {tasks.map((t) => {
            const project = projects.find((p) => p.id === t.project_id);
            return (
              <section
                key={t.id}
                className="rounded-2xl border border-border bg-surface px-4 py-3.5 transition-colors hover:border-accent"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-muted text-accent">
                      <ClockIcon className="h-5 w-5" />
                    </div>
                    <div className="min-w-0 pt-0.5">
                      <div className="flex flex-wrap items-center gap-2">
                        <Text weight="semibold" className="max-w-full truncate">
                        {t.prompt}
                        </Text>
                        <Badge variant={t.enabled ? "blue" : "neutral"} label={describeSchedule(t)} />
                        {!t.enabled && <Badge variant="neutral" label="désactivée" />}
                      </div>
                      <Text size="2xs" color="secondary" className="mt-1 block">
                        Projet : {project?.name ?? t.project_id}
                      </Text>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Text size="2xs" color="secondary" className="hidden sm:block">Activée</Text>
                    <Switch
                      label={`Activer la tâche ${t.prompt}`}
                      isLabelHidden
                      value={t.enabled}
                      isDisabled={updatingId === t.id}
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
                      isDisabled={updatingId === t.id}
                      onClick={() => {
                        setDeletingId(t.id);
                      }}
                    />
                  </div>
                </div>
                <div className="mt-3 grid grid-cols-1 gap-2 rounded-xl bg-muted px-3 py-2.5 sm:grid-cols-2">
                  <div>
                    <Text size="2xs" color="secondary" className="block uppercase tracking-wide">Prochaine exécution</Text>
                    <Text size="2xs" className="mt-0.5 block">{formatDateTime(t.next_run)}</Text>
                  </div>
                  <div>
                    <Text size="2xs" color="secondary" className="block uppercase tracking-wide">Dernière exécution</Text>
                    <Text size="2xs" className="mt-0.5 block">{t.last_run ? formatDateTime(t.last_run) : "Pas encore exécutée"}</Text>
                  </div>
                </div>
              </section>
            );
          })}
        </div>
      ) : null}

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
