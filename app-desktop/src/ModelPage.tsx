import { useEffect, useMemo, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { TextInput } from "@astryxdesign/core/TextInput";
import { Switch } from "@astryxdesign/core/Switch";
import { Table, proportional, pixel, type TableColumn } from "@astryxdesign/core/Table";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { ArrowLeftIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface ModelInfo {
  [key: string]: unknown;
  id: string;
  name: string;
  context_length: number;
  prompt_price: number;
  completion_price: number;
  supports_tools: boolean;
}

interface ModelPageProps {
  onBack: () => void;
}

function formatContextLength(n: number): string {
  if (n <= 0) return "-";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 1)}M`;
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`;
  return String(n);
}

function formatPrice(price: number): string {
  if (price === 0) return "gratuit";
  return `$${price < 1 ? price.toFixed(3) : price.toFixed(2)}`;
}

export function ModelPage({ onBack }: ModelPageProps) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [toolsOnly, setToolsOnly] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);

  // pas d'appel synchrone a setLoading()/setError() ici (seulement dans les
  // callbacks), pour pouvoir etre utilisee telle quelle dans l'effet de
  // montage (voir LogsPage.tsx / ProjectFilePanel.tsx).
  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/openrouter/models`).then(
        (r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))) as Promise<ModelInfo[]>,
      ),
      fetch(`${API_BASE}/settings/model`).then(
        (r) => (r.ok ? r.json() : { model: null }) as Promise<{ model: string | null }>,
      ),
    ])
      .then(([modelsData, settingsData]) => {
        setModels(modelsData);
        setCurrentModel(settingsData.model);
      })
      .catch(() => {
        setError("impossible de récupérer la liste des modèles depuis OpenRouter.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  async function selectModel(id: string) {
    setSavingId(id);
    try {
      const res = await fetch(`${API_BASE}/settings/model`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: id }),
      });
      if (res.ok) setCurrentModel(id);
    } finally {
      setSavingId(null);
    }
  }

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return models
      .filter((m) => !toolsOnly || m.supports_tools)
      .filter((m) => !q || m.id.toLowerCase().includes(q) || m.name.toLowerCase().includes(q))
      .sort((a, b) => a.prompt_price - b.prompt_price);
  }, [models, search, toolsOnly]);

  const columns: TableColumn<ModelInfo>[] = [
    {
      key: "name",
      header: "Modèle",
      width: proportional(3),
      renderCell: (m) => (
        <div className="min-w-0">
          <Text size="sm" weight="medium" className="block truncate">
            {m.name}
          </Text>
          <Text size="2xs" color="secondary" className="block truncate">
            {m.id}
          </Text>
        </div>
      ),
    },
    {
      key: "context",
      header: "Contexte",
      width: pixel(90),
      align: "end",
      renderCell: (m) => <Text size="sm">{formatContextLength(m.context_length)}</Text>,
    },
    {
      key: "prompt_price",
      header: "Entrée /M",
      width: pixel(100),
      align: "end",
      renderCell: (m) => <Text size="sm">{formatPrice(m.prompt_price)}</Text>,
    },
    {
      key: "completion_price",
      header: "Sortie /M",
      width: pixel(100),
      align: "end",
      renderCell: (m) => <Text size="sm">{formatPrice(m.completion_price)}</Text>,
    },
    {
      key: "tools",
      header: "Outils",
      width: pixel(90),
      align: "center",
      renderCell: (m) =>
        m.supports_tools ? (
          <Badge variant="success" label="oui" />
        ) : (
          <Badge variant="neutral" label="non" />
        ),
    },
    {
      key: "action",
      header: "",
      width: pixel(110),
      align: "end",
      renderCell: (m) =>
        m.id === currentModel ? (
          <Badge variant="success" label="actuel" />
        ) : (
          <Button
            label="Choisir"
            variant="secondary"
            size="sm"
            isDisabled={!m.supports_tools}
            isLoading={savingId === m.id}
            onClick={() => { void selectModel(m.id); }}
          />
        ),
    },
  ];

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6 flex items-center gap-3">
        <IconButton
          label="Retour"
          icon={<ArrowLeftIcon />}
          variant="ghost"
          size="sm"
          onClick={onBack}
        />
        <Text size="lg" weight="semibold">
          Modèle
        </Text>
      </div>

      <Text size="sm" color="secondary" className="mb-4 block">
        Modèles disponibles via OpenRouter, avec leur prix par million de tokens. Un modèle sans
        support des outils ne peut pas être sélectionné : la boucle agentique du harness en
        dépend entièrement.
      </Text>

      <div className="mb-4 flex items-center gap-3">
        <TextInput
          value={search}
          onChange={setSearch}
          placeholder="Rechercher un modèle (nom ou id)..."
          isLabelHidden
          label="Rechercher un modèle"
          size="sm"
          className="flex-1"
        />
        <Switch label="Outils uniquement" value={toolsOnly} onChange={setToolsOnly} size="sm" />
      </div>

      {error && (
        <Text size="sm" className="block text-error">
          {error}
        </Text>
      )}

      {!error && !loading && filtered.length === 0 && (
        <EmptyState title="Aucun modèle" description="Aucun modèle ne correspond à ce filtre." />
      )}

      {!error && filtered.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-default">
          <Table data={filtered} columns={columns} density="compact" hasHover />
        </div>
      )}
    </div>
  );
}
