import { useEffect, useState, type ReactNode } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";

const API_BASE = "http://127.0.0.1:8000";

interface ApiKeyFieldProps {
  title: string;
  description: ReactNode;
  /** Chemin de l'endpoint GET/PUT pour cette cle (meme forme des deux
   * cotes : GET -> {configured}, PUT {api_key} -> {configured}). */
  endpoint: string;
  placeholder: string;
}

/** Un bloc cle API reutilisable (OpenRouter, Tavily...) : jamais
 * pre-rempli avec la vraie valeur (le backend ne la renvoie jamais non
 * plus), juste un champ mot de passe vide et un badge qui dit si une cle
 * est deja active. */
function ApiKeyField({ title, description, endpoint, placeholder }: ApiKeyFieldProps) {
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
        // API hors ligne : le statut reste inconnu
      });
  }, [endpoint]);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}${endpoint}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
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
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <Text size="sm" weight="semibold">
          {title}
        </Text>
        {configured !== null && (
          <Badge
            variant={configured ? "success" : "error"}
            label={configured ? "configurée" : "non configurée"}
          />
        )}
      </div>

      <Text size="sm" color="secondary" className="mb-3 block">
        {description}
      </Text>

      <div className="flex items-end gap-3">
        <TextInput
          value={apiKey}
          onChange={setApiKey}
          type="password"
          placeholder={configured ? "•••••••••••••••• (déjà configurée)" : placeholder}
          isLabelHidden
          label={`Clé API ${title}`}
          className="flex-1"
        />
        <Button
          label="Enregistrer"
          variant="primary"
          isLoading={saving}
          isDisabled={!apiKey.trim()}
          onClick={() => {
            void save();
          }}
        />
      </div>
      {saved && (
        <Text size="2xs" color="secondary" className="mt-2 block">
          Clé enregistrée.
        </Text>
      )}
    </div>
  );
}

export function ApiKeySettings() {
  return (
    <div>
      <Text size="lg" weight="semibold" className="mb-4 block">
        Clés API
      </Text>

      <div className="flex flex-col gap-8">
        <ApiKeyField
          title="OpenRouter"
          endpoint="/settings/api_key"
          placeholder="sk-or-v1-..."
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

        <ApiKeyField
          title="Tavily (recherche web)"
          endpoint="/settings/tavily_key"
          placeholder="tvly-..."
          description={
            <>
              Clé{" "}
              <a
                href="https://app.tavily.com"
                target="_blank"
                rel="noreferrer"
                className="underline"
              >
                Tavily
              </a>{" "}
              utilisée en priorité par l'outil de recherche web (résultats avec extraits de
              contenu, pas juste des liens). Optionnelle : sans elle, ou si les crédits sont
              épuisés, la recherche retombe automatiquement sur un scraping de DuckDuckGo.
            </>
          }
        />
      </div>
    </div>
  );
}
