import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import {
  Selector,
  SelectorOption,
  type SelectorOptionData,
  type SelectorOptionType,
} from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import {
  BrainIcon,
  FileIcon,
  NetworkIcon,
  RefreshIcon,
  SearchIcon,
  TerminalIcon,
} from "./icons";
import { familyInfo, familyKey, isModelFamilyVisible } from "./modelFamilies";

import { API_BASE } from "./api";

interface RoleModelInfo {
  role: string;
  default_model: string;
  model: string;
  is_override: boolean;
}

interface ModelInfo {
  id: string;
  name: string;
  supports_tools: boolean;
}

interface RolePresentation {
  label: string;
  description: string;
  icon: ReactNode;
}

const ROLE_PRESENTATIONS: Record<string, RolePresentation> = {
  orchestrator: {
    label: "Planificateur",
    description: "Découpe la tâche, distribue le travail et synthétise les résultats.",
    icon: <NetworkIcon className="h-5 w-5" />,
  },
  conversational: {
    label: "Conversationnel",
    description: "Rédaction et raisonnement général, hors code et recherche.",
    icon: <BrainIcon className="h-5 w-5" />,
  },
  code: {
    label: "Code",
    description: "Lit, analyse et modifie le code lorsque le projet l'autorise.",
    icon: <TerminalIcon className="h-5 w-5" />,
  },
  research: {
    label: "Recherche",
    description: "Explore le web, les fichiers et les sources externes.",
    icon: <SearchIcon className="h-5 w-5" />,
  },
  vision: {
    label: "Vision",
    description: "Analyse les images et les PDF référencés dans la tâche.",
    icon: <FileIcon className="h-5 w-5" />,
  },
};

function rolePresentation(role: string): RolePresentation {
  return (
    ROLE_PRESENTATIONS[role] ?? {
      label: role,
      description: "Rôle personnalisé du mode multi-agent.",
      icon: <NetworkIcon className="h-5 w-5" />,
    }
  );
}

function modelDisplayName(model: ModelInfo | undefined, modelId: string): string {
  if (model?.name.trim()) return model.name;
  const parts = modelId.split("/");
  return parts[parts.length - 1] ?? modelId;
}

function renderModelOption(
  option: SelectorOptionData,
  modelsById: Map<string, ModelInfo>,
): ReactNode {
  const model = modelsById.get(option.value);
  const info = familyInfo(familyKey(option.value));
  return (
    <SelectorOption
      icon={<Avatar name="" src={info.logo} size="md" tooltip={false} />}
      label={modelDisplayName(model, option.value)}
      description={<span className="font-mono text-[11px]">{option.value}</span>}
    />
  );
}

/** Un modèle par rôle du mode multi-agent (/multi-agents), persisté dans
 * settings.json (voir model_roles.py). Les choix viennent du catalogue
 * OpenRouter et restent limités aux modèles capables d'appeler des outils. */
export function RoleModelsSettings() {
  const [roles, setRoles] = useState<RoleModelInfo[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingRole, setSavingRole] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
        setError("Impossible de charger les modèles des rôles.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  // Une valeur enregistrée reste visible même si OpenRouter la retire ensuite
  // du catalogue ou si elle ne déclare plus le support des outils.
  const selectableModels = useMemo(() => {
    const byId = new Map(
      models
        .filter((model) => model.supports_tools && isModelFamilyVisible(model.id))
        .map((model) => [model.id, model]),
    );
    for (const role of roles) {
      if (!byId.has(role.model) && isModelFamilyVisible(role.model)) {
        byId.set(role.model, { id: role.model, name: role.model, supports_tools: true });
      }
    }
    return [...byId.values()];
  }, [models, roles]);

  const modelsById = useMemo(
    () => new Map(selectableModels.map((model) => [model.id, model])),
    [selectableModels],
  );

  const groupedToolModels = useMemo(() => {
    const byFamily = new Map<string, ModelInfo[]>();
    for (const model of selectableModels) {
      const key = familyKey(model.id);
      const list = byFamily.get(key) ?? [];
      list.push(model);
      byFamily.set(key, list);
    }
    for (const list of byFamily.values()) {
      list.sort((a, b) => modelDisplayName(a, a.id).localeCompare(modelDisplayName(b, b.id)));
    }
    return [...byFamily.entries()].sort(([a], [b]) =>
      familyInfo(a).label.localeCompare(familyInfo(b).label),
    );
  }, [selectableModels]);

  const modelOptions = useMemo<SelectorOptionType[]>(
    () =>
      groupedToolModels.map(([key, list]) => ({
        type: "section",
        title: familyInfo(key).label,
        options: list.map((model) => ({
          value: model.id,
          // Le filtre du Selector ne recherche que label : nom + id gardent
          // donc les deux façons habituelles de retrouver un modèle.
          label: `${modelDisplayName(model, model.id)} ${model.id}`,
        })),
      })),
    [groupedToolModels],
  );

  async function updateRole(role: string, model: string | null) {
    setSavingRole(role);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/settings/role_models`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role, model }),
      });
      if (!res.ok) throw new Error("role model update failed");
      setRoles((await res.json()) as RoleModelInfo[]);
    } catch {
      setError("Impossible d'enregistrer ce modèle. Réessaie dans un instant.");
    } finally {
      setSavingRole(null);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-4 pr-8">
        <div>
          <Text size="lg" weight="semibold" className="mb-1 block">
            Modèles des rôles
          </Text>
          <Text size="sm" color="secondary" className="block max-w-xl">
            Choisis le modèle le plus adapté à chaque spécialité du mode multi-agent. Seuls les
            modèles compatibles avec les outils sont proposés.
          </Text>
        </div>
        {!loading && roles.length > 0 && (
          <Badge variant="blue" label={`${roles.length} rôles`} className="shrink-0" />
        )}
      </div>

      <div className="mb-4 flex items-start gap-3 rounded-xl bg-accent-muted px-4 py-3">
        <div className="mt-0.5 shrink-0 text-accent">
          <NetworkIcon className="h-4 w-4" />
        </div>
        <Text size="2xs" color="secondary">
          Chaque rôle peut utiliser un fournisseur différent. Le changement est enregistré
          immédiatement et s'applique au prochain run <code>/multi-agents</code>.
        </Text>
      </div>

      {error && (
        <Text size="sm" className="mb-3 block text-error">
          {error}
        </Text>
      )}

      {loading && (
        <div className="flex flex-col gap-3" role="status" aria-label="Chargement des rôles">
          {[0, 1, 2, 3].map((item) => (
            <div
              key={item}
              className="h-24 animate-pulse rounded-2xl border border-border bg-muted"
            />
          ))}
        </div>
      )}

      {!loading && roles.length === 0 && !error && (
        <EmptyState
          title="Aucun rôle disponible"
          description="Ajoute d'abord un rôle multi-agent pour pouvoir lui attribuer un modèle."
        />
      )}

      {!loading && roles.length > 0 && (
        <div className="flex flex-col gap-3">
          {roles.map((role) => {
            const presentation = rolePresentation(role.role);
            return (
              <section
                key={role.role}
                className="grid grid-cols-1 items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-3.5 transition-colors hover:border-accent md:grid-cols-[minmax(0,0.9fr)_minmax(280px,1.25fr)] md:gap-5"
              >
                <div className="flex min-w-0 items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-muted text-accent">
                    {presentation.icon}
                  </div>
                  <div className="min-w-0 pt-0.5">
                    <div className="mb-0.5 flex flex-wrap items-center gap-2">
                      <Text weight="semibold">{presentation.label}</Text>
                      <Badge
                        variant={role.is_override ? "blue" : "neutral"}
                        label={role.is_override ? "personnalisé" : "par défaut"}
                      />
                    </div>
                    <Text size="2xs" color="secondary" className="block leading-relaxed">
                      {presentation.description}
                    </Text>
                  </div>
                </div>

                <div className="min-w-0">
                  <div className="mb-1.5 flex items-center justify-between gap-2">
                    <Text size="2xs" color="secondary" className="uppercase tracking-wide">
                      Modèle assigné
                    </Text>
                    {role.is_override && (
                      <IconButton
                        label={`Réinitialiser sur ${role.default_model}`}
                        icon={<RefreshIcon />}
                        variant="ghost"
                        size="sm"
                        isDisabled={savingRole === role.role}
                        onClick={() => {
                          void updateRole(role.role, null);
                        }}
                      />
                    )}
                  </div>
                  <Selector
                    label={`Modèle du rôle ${presentation.label}`}
                    isLabelHidden
                    options={modelOptions}
                    value={role.model}
                    onChange={(model) => {
                      void updateRole(role.role, model);
                    }}
                    renderOption={(option) => renderModelOption(option, modelsById)}
                    renderValue={(option) => renderModelOption(option, modelsById)}
                    hasSearch
                    searchPlaceholder="Rechercher un modèle..."
                    size="sm"
                    width="100%"
                    isLoading={savingRole === role.role}
                    isDisabled={savingRole === role.role}
                  />
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
