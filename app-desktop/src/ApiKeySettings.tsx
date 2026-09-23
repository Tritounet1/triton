import { useEffect, useState, type ReactNode } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { KeyIcon } from "./icons";

import { API_BASE } from "./api";

interface ApiKeyFieldProps {
  title: string;
  description: ReactNode;
  /** Chemin de l'endpoint GET/PUT pour cette cle (meme forme des deux
   * cotes : GET -> {configured}, PUT {api_key} -> {configured}). */
  endpoint: string;
  placeholder: string;
  isRequired?: boolean;
}

/** Un bloc cle API reutilisable (OpenRouter, Tavily...) : jamais
 * pre-rempli avec la vraie valeur (le backend ne la renvoie jamais non
 * plus), juste un champ mot de passe vide et un badge qui dit si une cle
 * est deja active. */
export function ApiKeyField({ title, description, endpoint, placeholder, isRequired = false }: ApiKeyFieldProps) {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}${endpoint}`)
      .then((r) => (r.ok ? r.json() : { configured: false }))
      .then((data: { configured: boolean }) => {
        setConfigured(data.configured);
      })
      .catch(() => {
        // offline: status stays unknown
      });
  }, [endpoint]);

  async function save(value = apiKey) {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: value }),
      });
      if (res.ok) {
        const data = (await res.json()) as { configured: boolean };
        setConfigured(data.configured);
        setApiKey("");
        setSaved(true);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="rounded-2xl border border-border bg-surface px-4 py-4 transition-colors hover:border-accent">
      <div className="mb-4 flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-muted text-accent">
          <KeyIcon className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <Text weight="semibold">{title}</Text>
            {isRequired && <Badge variant="blue" label="requis" />}
            {configured !== null && (
              <Badge
                variant={configured ? "success" : "neutral"}
                label={configured ? "configurée" : "non configurée"}
              />
            )}
          </div>
          <Text size="2xs" color="secondary" className="mt-1 block">
            {description}
          </Text>
        </div>
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <TextInput
          value={apiKey}
          onChange={setApiKey}
          type="password"
          placeholder={configured ? "•••••••••••••••• (déjà configurée)" : placeholder}
          isLabelHidden
          label={`Clé API ${title}`}
          className="flex-1 font-mono"
        />
        <Button
          label="Enregistrer"
          variant="primary"
          size="sm"
          className="shrink-0"
          isLoading={saving}
          isDisabled={!apiKey.trim()}
          onClick={() => {
            void save();
          }}
        />
        {configured && (
          <Button
            label="Effacer"
            variant="secondary"
            size="sm"
            className="shrink-0"
            isLoading={saving}
            onClick={() => {
              void save("");
            }}
          />
        )}
      </div>
      {saved && (
        <Text size="2xs" className="mt-2 block text-success">
          Clé enregistrée et active immédiatement.
        </Text>
      )}
    </section>
  );
}

export function ApiKeySettings() {
  return (
    <div>
      <div className="mb-4 pr-8">
        <Text size="lg" weight="semibold" className="mb-1 block">
          Clé API
        </Text>
        <Text size="sm" color="secondary" className="block max-w-xl">
          Configure l'accès utilisé par Triton. La clé est conservée localement et n'est jamais
          réaffichée après enregistrement.
        </Text>
      </div>

      <div className="mb-4 flex items-start gap-3 rounded-xl bg-accent-muted px-4 py-3">
        <div className="mt-0.5 shrink-0 text-accent">
          <KeyIcon className="h-4 w-4" />
        </div>
        <Text size="2xs" color="secondary">
          Colle une nouvelle clé pour la remplacer, ou efface une clé optionnelle. Le changement
          prend effet immédiatement, sans redémarrer l'application.
        </Text>
      </div>

      <ApiKeyField
        title="OpenRouter"
        endpoint="/settings/api_key"
        placeholder="sk-or-v1-..."
        isRequired
        description={
          <>
            Clé{" "}
            <a
              href="https://openrouter.ai/settings/keys"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              OpenRouter
            </a>{" "}
            utilisée pour tous les appels au modèle. Enregistrée ici, elle prend effet
            immédiatement, sans redémarrer l'application. Obligatoire pour discuter.
          </>
        }
      />
    </div>
  );
}
