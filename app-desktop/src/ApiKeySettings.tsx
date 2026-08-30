import { useEffect, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";

const API_BASE = "http://127.0.0.1:8000";

/** Jamais pre-remplie avec la vraie valeur (le backend ne la renvoie
 * jamais non plus, voir GET /settings/api_key) : juste un champ mot de
 * passe vide, et un badge qui dit si une cle est deja active. */
export function ApiKeySettings() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch(`${API_BASE}/settings/api_key`)
      .then((r) => (r.ok ? r.json() : { configured: false }))
      .then((data: { configured: boolean }) => {
        setConfigured(data.configured);
      })
      .catch(() => {
        // API hors ligne : le statut reste inconnu
      });
  }, []);

  async function save() {
    setSaving(true);
    setSaved(false);
    try {
      const res = await fetch(`${API_BASE}/settings/api_key`, {
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
      <div className="mb-4 flex items-center justify-between gap-3">
        <Text size="lg" weight="semibold">
          Clé API
        </Text>
        {configured !== null && (
          <Badge
            variant={configured ? "success" : "error"}
            label={configured ? "configurée" : "non configurée"}
          />
        )}
      </div>

      <Text size="sm" color="secondary" className="mb-4 block">
        Clé API{" "}
        <a
          href="https://openrouter.ai/settings/keys"
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          OpenRouter
        </a>{" "}
        utilisée pour tous les appels au modèle. Enregistrée ici, elle prend effet immédiatement,
        sans redémarrer l'application.
      </Text>

      <div className="flex items-end gap-3">
        <TextInput
          value={apiKey}
          onChange={setApiKey}
          type="password"
          placeholder={configured ? "•••••••••••••••• (déjà configurée)" : "sk-or-v1-..."}
          isLabelHidden
          label="Clé API OpenRouter"
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
