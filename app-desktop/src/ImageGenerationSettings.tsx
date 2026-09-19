import { Avatar } from "@astryxdesign/core/Avatar";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { useEffect, useMemo, useState } from "react";
import { CheckIcon, ImageIcon, SearchIcon } from "./icons";
import { modelAvatar } from "./modelFamilies";

const API_BASE = "http://127.0.0.1:8000";

interface ImageModel {
  id: string;
  name: string;
  description: string;
}

/** Choix persistant du modele image. Les choix faits dans le compositeur
 * restent ponctuels et ne passent jamais par ce composant. */
export function ImageGenerationSettings({ onModelChanged }: { onModelChanged: () => void }) {
  const [models, setModels] = useState<ImageModel[]>([]);
  const [currentModel, setCurrentModel] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/openrouter/image-models`).then((r) =>
        r.ok ? (r.json() as Promise<ImageModel[]>) : Promise.reject(new Error(String(r.status))),
      ),
      fetch(`${API_BASE}/settings/image_model`).then((r) =>
        r.ok
          ? (r.json() as Promise<{ model: string }>)
          : Promise.reject(new Error(String(r.status))),
      ),
    ])
      .then(([catalog, settings]) => {
        setModels(catalog);
        setCurrentModel(settings.model);
      })
      .catch(() => {
        setError("Impossible de récupérer les modèles de génération d’images.");
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return models.filter(
      (model) =>
        !query ||
        model.id.toLowerCase().includes(query) ||
        model.name.toLowerCase().includes(query),
    );
  }, [models, search]);

  async function selectModel(model: ImageModel) {
    setSavingId(model.id);
    try {
      const response = await fetch(`${API_BASE}/settings/image_model`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model.id }),
      });
      if (!response.ok) throw new Error(String(response.status));
      setCurrentModel(model.id);
      onModelChanged();
    } catch {
      setError("Impossible d’enregistrer ce modèle d’image.");
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="pr-8">
      <div className="mb-6">
        <div className="mb-2 flex items-center gap-2">
          <div className="rounded-lg bg-accent-muted p-2 text-accent">
            <ImageIcon className="h-5 w-5" />
          </div>
          <Text size="lg" weight="semibold">Génération d’images</Text>
        </div>
        <Text size="sm" color="secondary">
          Ce modèle est utilisé par défaut quand tu passes le compositeur en mode image.
          Tu peux toujours en choisir un autre pour une seule génération, sans modifier ce réglage.
        </Text>
      </div>

      <TextInput
        value={search}
        onChange={setSearch}
        label="Rechercher un modèle d’image"
        isLabelHidden
        placeholder="Rechercher un modèle…"
        startIcon={<SearchIcon className="h-4 w-4 text-secondary" />}
        size="sm"
        className="mb-4"
      />

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="sm" aria-label="Chargement des modèles" /></div>
      ) : error ? (
        <div className="rounded-xl border border-error/30 bg-error-muted px-4 py-3 text-sm text-error">{error}</div>
      ) : filtered.length === 0 ? (
        <EmptyState title="Aucun modèle" description="Essaie une autre recherche." />
      ) : (
        <div className="flex flex-col gap-2">
          {filtered.map((model) => {
            const selected = model.id === currentModel;
            const avatar = modelAvatar(model.id);
            return (
              <div
                key={model.id}
                className={`flex items-center gap-3 rounded-xl border p-3 transition-colors ${
                  selected ? "border-accent bg-accent-muted" : "border-border bg-surface hover:bg-surface-raised"
                }`}
              >
                <Avatar name={avatar.name} src={avatar.logo} size="sm" />
                <div className="min-w-0 flex-1">
                  <Text size="sm" weight="semibold" className="block truncate">{model.name}</Text>
                  <Text size="2xs" color="secondary" className="block truncate">{model.id}</Text>
                  {model.description && (
                    <Text size="2xs" color="secondary" className="mt-1 block line-clamp-2">{model.description}</Text>
                  )}
                </div>
                {selected ? (
                  <Badge variant="success" label="Par défaut" />
                ) : (
                  <Button
                    label="Choisir"
                    variant="secondary"
                    size="sm"
                    isLoading={savingId === model.id}
                    isDisabled={savingId !== null}
                    onClick={() => { void selectModel(model); }}
                  />
                )}
                {selected && <CheckIcon className="h-4 w-4 shrink-0 text-accent" />}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
