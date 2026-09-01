import { useEffect, useMemo, useState } from "react";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { RefreshIcon } from "./icons";
import { familyInfo, familyKey } from "./modelFamilies";

const API_BASE = "http://127.0.0.1:8000";

interface RoleModelInfo {
  role: string;
  default_model: string;
  model: string;
  is_override: boolean;
}

interface ModelInfo {
  id: string;
  supports_tools: boolean;
}

const ROLE_LABELS: Record<string, string> = {
  orchestrator: "Planificateur",
  conversational: "Conversationnel",
  code: "Code",
  research: "Recherche",
  vision: "Vision",
};

const ROLE_DESCRIPTIONS: Record<string, string> = {
  orchestrator: "Découpe la tâche en sous-tâches et synthétise les résultats.",
  conversational: "Rédaction, raisonnement général - tout ce qui n'est ni code ni recherche.",
  code: "Lit, analyse et (si un projet est sélectionné) écrit du code.",
  research: "Recherche web, lecture de fichiers et d'URLs.",
  vision: "Analyse une image ou un PDF déjà référencé dans la tâche.",
};

/** Un modele par role du mode multi-agent (/multi-agents), persiste dans
 * settings.json (voir model_roles.py) : le select de chaque role est
 * alimente par /openrouter/models (deja utilise par ModelSettings),
 * filtre aux modeles supportant les tools puisqu'un role sans ca ne
 * fonctionnerait pas dans la boucle agentique. */
export function RoleModelsSettings() {
  const [roles, setRoles] = useState<RoleModelInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingRole, setSavingRole] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/settings/role_models`).then((r) => (r.ok ? r.json() : [])),
      fetch(`${API_BASE}/openrouter/models`).then((r) => (r.ok ? r.json() : [])),
    ])
      .then(([rolesData, modelsData]: [RoleModelInfo[], ModelInfo[]]) => {
        setRoles(rolesData);
        setModels(modelsData);
      })
      .catch(() => {
        // API hors ligne : les listes restent vides
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const groupedToolModels = useMemo(() => {
    const byFamily = new Map<string, ModelInfo[]>();
    for (const m of models) {
      if (!m.supports_tools) continue;
      const key = familyKey(m.id);
      const list = byFamily.get(key) ?? [];
      list.push(m);
      byFamily.set(key, list);
    }
    for (const list of byFamily.values()) list.sort((a, b) => a.id.localeCompare(b.id));
    return [...byFamily.entries()].sort(([a], [b]) =>
      familyInfo(a).label.localeCompare(familyInfo(b).label),
    );
  }, [models]);

  async function updateRole(role: string, model: string | null) {
    setSavingRole(role);
    try {
      const res = await fetch(`${API_BASE}/settings/role_models`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, model }),
      });
      if (res.ok) setRoles((await res.json()) as RoleModelInfo[]);
    } finally {
      setSavingRole(null);
    }
  }

  return (
    <div>
      <Text size="lg" weight="semibold" className="mb-1 block">
        Rôles multi-agent
      </Text>
      <Text size="sm" color="secondary" className="mb-4 block">
        Modèle utilisé par chaque rôle du mode multi-agent (
        <code className="rounded bg-muted px-1 py-0.5 text-xs">/multi-agents</code>).
      </Text>

      {!loading && (
        <div className="flex flex-col gap-2">
          {roles.map((r) => (
            <div
              key={r.role}
              className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface px-4 py-3"
            >
              <div className="min-w-0 flex-1">
                <Text weight="medium" className="block">
                  {ROLE_LABELS[r.role] ?? r.role}
                </Text>
                <Text size="2xs" color="secondary" className="block">
                  {ROLE_DESCRIPTIONS[r.role]}
                </Text>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <select
                  value={r.model}
                  disabled={savingRole === r.role}
                  onChange={(e) => {
                    void updateRole(r.role, e.target.value);
                  }}
                  className="max-w-80 rounded-lg border border-border bg-transparent px-2 py-1.5 text-sm"
                >
                  {groupedToolModels.map(([key, list]) => (
                    <optgroup key={key} label={familyInfo(key).label}>
                      {list.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
                {r.is_override && (
                  <IconButton
                    label="Réinitialiser au modèle par défaut"
                    icon={<RefreshIcon />}
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      void updateRole(r.role, null);
                    }}
                  />
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
