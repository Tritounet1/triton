import { useEffect, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { TextInput } from "@astryxdesign/core/TextInput";
import { TextArea } from "@astryxdesign/core/TextArea";
import { Switch } from "@astryxdesign/core/Switch";
import { Badge } from "@astryxdesign/core/Badge";
import { PencilIcon, TrashIcon, PlusIcon, RefreshIcon, ChevronRightIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface RoleConfig {
  id: string;
  label: string;
  description: string;
  can_write: boolean;
  system_prompt: string;
}

const EMPTY_DRAFT: RoleConfig = {
  id: "",
  label: "",
  description: "",
  can_write: false,
  system_prompt: "",
};

/** Le jeu de roles du mode multi-agent (/multi-agents) et le nombre max
 * de sous-taches par run - avant cette page, les deux etaient codes en
 * dur dans orchestrator.py (le jeu fixe code/research/vision/
 * conversational, et MAX_SUBTASKS=6). Remplace la liste entiere a chaque
 * sauvegarde (PUT /settings/multi_agent_roles) plutot que d'editer un
 * role a la fois cote serveur - plus simple, et la liste reste courte. */
export function MultiAgentRolesSettings() {
  const [roles, setRoles] = useState<RoleConfig[]>([]);
  const [maxSubtasks, setMaxSubtasksValue] = useState<number | null>(null);
  const [defaultMaxSubtasks, setDefaultMaxSubtasks] = useState(6);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<RoleConfig>(EMPTY_DRAFT);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/settings/multi_agent_roles`).then((r) =>
        r.ok ? (r.json() as Promise<RoleConfig[]>) : [],
      ),
      fetch(`${API_BASE}/settings/max_subtasks`).then((r) =>
        r.ok ? (r.json() as Promise<{ value: number; default: number }>) : { value: 6, default: 6 },
      ),
    ])
      .then(([rolesData, maxData]) => {
        setRoles(rolesData);
        setMaxSubtasksValue(maxData.value);
        setDefaultMaxSubtasks(maxData.default);
      })
      .catch(() => {
        // API hors ligne : les listes restent vides
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  async function persistRoles(next: RoleConfig[]) {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/multi_agent_roles`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ roles: next }),
      });
      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail ?? "impossible d'enregistrer ces rôles.");
        return;
      }
      setRoles((await res.json()) as RoleConfig[]);
      setEditingId(null);
    } finally {
      setSaving(false);
    }
  }

  async function resetRoles() {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/multi_agent_roles/reset`, { method: "POST" });
      if (res.ok) setRoles((await res.json()) as RoleConfig[]);
    } finally {
      setSaving(false);
    }
  }

  async function updateMaxSubtasks(value: number | null) {
    setMaxSubtasksValue(value);
    await fetch(`${API_BASE}/settings/max_subtasks`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ value }),
    });
  }

  function startEdit(role: RoleConfig) {
    setDraft(role);
    setEditingId(role.id);
    setError(null);
  }

  function startAdd() {
    setDraft(EMPTY_DRAFT);
    setEditingId("__new__");
    setError(null);
  }

  function saveDraft() {
    const id = draft.id.trim();
    if (!id || !draft.label.trim()) {
      setError("id et label sont obligatoires.");
      return;
    }
    const isNew = editingId === "__new__";
    const others = roles.filter((r) => r.id !== editingId);
    if (others.some((r) => r.id === id)) {
      setError("cet id est déjà utilisé par un autre rôle.");
      return;
    }
    const next = isNew
      ? [...roles, { ...draft, id }]
      : roles.map((r) => (r.id === editingId ? { ...draft, id } : r));
    void persistRoles(next);
  }

  function deleteRole(id: string) {
    void persistRoles(roles.filter((r) => r.id !== id));
  }

  return (
    <div>
      <Text size="lg" weight="semibold" className="mb-1 block">
        Rôles multi-agent
      </Text>
      <Text size="sm" color="secondary" className="mb-4 block">
        Les rôles que le planificateur peut attribuer à une sous-tâche (
        <code className="rounded bg-muted px-1 py-0.5 text-xs">/multi-agents</code>), et combien
        de sous-tâches un run peut créer au maximum. Le modèle utilisé par chaque rôle se règle
        dans « Rôles multi-agent » (modèles), à part.
      </Text>

      {!loading && (
        <>
          <div className="mb-4 flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3">
            <div className="min-w-0">
              <Text weight="medium" className="block">
                Sous-tâches maximum par run
              </Text>
              <Text size="2xs" color="secondary" className="block">
                Par défaut : {defaultMaxSubtasks}
              </Text>
            </div>
            <TextInput
              value={String(maxSubtasks ?? defaultMaxSubtasks)}
              onChange={(v) => {
                const n = Number.parseInt(v, 10);
                void updateMaxSubtasks(Number.isFinite(n) && n > 0 ? n : null);
              }}
              isLabelHidden
              label="Sous-tâches maximum par run"
              size="sm"
              className="w-20"
            />
          </div>

          {error && (
            <Text size="sm" className="mb-3 block text-error">
              {error}
            </Text>
          )}

          <div className="mb-3 flex flex-col gap-2">
            {roles.map((role) => (
              <div key={role.id} className="overflow-hidden rounded-xl border border-border">
                <div className="flex items-center gap-3 bg-surface px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <Text weight="medium">{role.label}</Text>
                      <Text size="2xs" color="secondary" className="font-mono">
                        {role.id}
                      </Text>
                      {role.can_write && <Badge variant="neutral" label="écriture" />}
                    </div>
                    <Text size="2xs" color="secondary" className="mt-0.5 block truncate">
                      {role.description || "(pas de description)"}
                    </Text>
                  </div>
                  <IconButton
                    label="Modifier"
                    icon={<PencilIcon />}
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      startEdit(role);
                    }}
                  />
                  <IconButton
                    label="Supprimer"
                    icon={<TrashIcon />}
                    variant="ghost"
                    size="sm"
                    isDisabled={roles.length <= 1}
                    onClick={() => {
                      deleteRole(role.id);
                    }}
                  />
                  <ChevronRightIcon
                    className={`h-4 w-4 shrink-0 text-secondary transition-transform ${editingId === role.id ? "rotate-90" : ""}`}
                  />
                </div>
                {editingId === role.id && (
                  <div className="flex flex-col gap-3 border-t border-border px-4 py-3">
                    <RoleEditForm draft={draft} setDraft={setDraft} />
                    <div className="flex justify-end gap-2">
                      <Button
                        label="Annuler"
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          setEditingId(null);
                        }}
                      />
                      <Button
                        label="Enregistrer"
                        variant="primary"
                        size="sm"
                        isLoading={saving}
                        onClick={saveDraft}
                      />
                    </div>
                  </div>
                )}
              </div>
            ))}

            {editingId === "__new__" && (
              <div className="overflow-hidden rounded-xl border border-border">
                <div className="flex flex-col gap-3 px-4 py-3">
                  <RoleEditForm draft={draft} setDraft={setDraft} />
                  <div className="flex justify-end gap-2">
                    <Button
                      label="Annuler"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditingId(null);
                      }}
                    />
                    <Button
                      label="Ajouter"
                      variant="primary"
                      size="sm"
                      isLoading={saving}
                      onClick={saveDraft}
                    />
                  </div>
                </div>
              </div>
            )}
          </div>

          <div className="flex gap-2">
            <Button
              label="Ajouter un rôle"
              variant="secondary"
              size="sm"
              icon={<PlusIcon className="h-4 w-4" />}
              isDisabled={editingId !== null}
              onClick={startAdd}
            />
            <Button
              label="Réinitialiser aux rôles par défaut"
              variant="ghost"
              size="sm"
              icon={<RefreshIcon className="h-4 w-4" />}
              onClick={() => {
                void resetRoles();
              }}
            />
          </div>
        </>
      )}
    </div>
  );
}

function RoleEditForm({
  draft,
  setDraft,
}: {
  draft: RoleConfig;
  setDraft: (d: RoleConfig) => void;
}) {
  return (
    <>
      <div className="flex gap-3">
        <TextInput
          value={draft.id}
          onChange={(v) => {
            setDraft({ ...draft, id: v });
          }}
          label="Id (utilisé par le planificateur, ex. code, research...)"
          size="sm"
          className="flex-1"
        />
        <TextInput
          value={draft.label}
          onChange={(v) => {
            setDraft({ ...draft, label: v });
          }}
          label="Nom affiché"
          size="sm"
          className="flex-1"
        />
      </div>
      <TextInput
        value={draft.description}
        onChange={(v) => {
          setDraft({ ...draft, description: v });
        }}
        label="Description (montrée au planificateur pour choisir ce rôle)"
        size="sm"
      />
      <TextArea
        value={draft.system_prompt}
        onChange={(v) => {
          setDraft({ ...draft, system_prompt: v });
        }}
        label="Instructions système additionnelles (optionnel)"
        placeholder="Ajoutées au prompt système de la sous-tâche, ex. « Réponds toujours en français. »"
        rows={2}
      />
      <Switch
        label="Peut écrire des fichiers (quand un projet est sélectionné)"
        value={draft.can_write}
        onChange={(v) => {
          setDraft({ ...draft, can_write: v });
        }}
        size="sm"
      />
    </>
  );
}
