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
import { ArrowLeftIcon, PlugIcon, PlusIcon, TrashIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface McpServer {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  connected: boolean;
  error: string | null;
  tools: string[];
}

interface McpServersPageProps {
  onBack: () => void;
}

function parseLines(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function parseEnv(text: string): Record<string, string> {
  const env: Record<string, string> = {};
  for (const line of parseLines(text)) {
    const idx = line.indexOf("=");
    if (idx === -1) continue;
    env[line.slice(0, idx).trim()] = line.slice(idx + 1).trim();
  }
  return env;
}

export function McpServersPage({ onBack }: McpServersPageProps) {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingName, setDeletingName] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [envText, setEnvText] = useState("");

  // pas d'appel synchrone a setLoading() ici (seulement dans les callbacks) :
  // react-hooks (set-state-in-effect) interdit setState synchrone dans un
  // effet, et loading demarre deja a true via son useState initial.
  useEffect(() => {
    fetch(`${API_BASE}/mcp/servers`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: McpServer[]) => { setServers(data); })
      .catch(() => { setServers([]); })
      .finally(() => { setLoading(false); });
  }, []);

  function resetForm() {
    setName("");
    setCommand("");
    setArgsText("");
    setEnvText("");
    setFormError(null);
    setShowForm(false);
  }

  async function submitForm() {
    if (!name.trim() || !command.trim()) {
      setFormError("le nom et la commande sont obligatoires.");
      return;
    }
    setSubmitting(true);
    setFormError(null);

    try {
      const res = await fetch(`${API_BASE}/mcp/servers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: name.trim(),
          command: command.trim(),
          args: parseLines(argsText),
          env: parseEnv(envText),
          enabled: true,
        }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setFormError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      const data = (await res.json()) as McpServer[];
      setServers(data);
      resetForm();
    } catch {
      setFormError("impossible de contacter l'API Triton (127.0.0.1:8000).");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleServer(server: McpServer) {
    const res = await fetch(`${API_BASE}/mcp/servers/${server.name}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !server.enabled }),
    });
    if (res.ok) setServers((await res.json()) as McpServer[]);
  }

  async function confirmDelete() {
    if (!deletingName) return;
    const res = await fetch(`${API_BASE}/mcp/servers/${deletingName}`, { method: "DELETE" });
    setDeletingName(null);
    if (res.ok) setServers((await res.json()) as McpServer[]);
  }

  return (
    <div className="mx-auto max-w-3xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <IconButton
            label="Retour"
            icon={<ArrowLeftIcon />}
            variant="ghost"
            size="sm"
            onClick={onBack}
          />
          <div className="flex items-center gap-2">
            <PlugIcon className="h-5 w-5 text-secondary" />
            <Text size="lg" weight="semibold">
              Serveurs MCP
            </Text>
          </div>
        </div>
        <Button
          label="Ajouter un serveur"
          icon={<PlusIcon />}
          variant="secondary"
          size="sm"
          onClick={() => { setShowForm((v) => !v); }}
        />
      </div>

      <Text size="sm" color="secondary" className="mb-6 block">
        Un serveur MCP expose des outils que le modèle peut utiliser, comme ceux codés à la main
        dans <code className="rounded bg-muted px-1 py-0.5 text-xs">tools.py</code>, mais fournis
        par un processus externe. Même format que la config Claude Desktop (commande, arguments,
        variables d'environnement).
      </Text>

      {showForm && (
        <div className="mb-6 rounded-xl border border-border bg-surface p-4">
          <div className="mb-3 grid grid-cols-2 gap-3">
            <TextInput
              label="Nom"
              value={name}
              onChange={setName}
              placeholder="mon-serveur"
              size="sm"
            />
            <TextInput
              label="Commande"
              value={command}
              onChange={setCommand}
              placeholder="npx, uvx, node..."
              size="sm"
            />
          </div>
          <div className="mb-3 grid grid-cols-2 gap-3">
            <TextArea
              label="Arguments (un par ligne)"
              value={argsText}
              onChange={setArgsText}
              rows={4}
              placeholder={"-y\nmon-package-mcp"}
            />
            <TextArea
              label="Variables d'environnement (CLE=valeur, une par ligne)"
              value={envText}
              onChange={setEnvText}
              rows={4}
              placeholder={"API_KEY=..."}
            />
          </div>
          {formError && (
            <Text size="sm" className="mb-3 block text-error">
              {formError}
            </Text>
          )}
          <div className="flex gap-2">
            <Button
              label="Ajouter et connecter"
              variant="primary"
              size="sm"
              isLoading={submitting}
              onClick={() => { void submitForm(); }}
            >
              Ajouter et connecter
            </Button>
            <Button label="Annuler" variant="ghost" size="sm" onClick={resetForm}>
              Annuler
            </Button>
          </div>
        </div>
      )}

      {!loading && servers.length === 0 && !showForm ? (
        <EmptyState
          title="Aucun serveur MCP configuré"
          description="Ajoute un serveur pour donner au modèle des outils supplémentaires, sans avoir à les coder toi-même."
        />
      ) : (
        <div className="space-y-2">
          {servers.map((s) => (
            <div key={s.name} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Text weight="semibold">{s.name}</Text>
                    {s.enabled ? (
                      s.connected ? (
                        <Badge variant="success" label={`${s.tools.length} outil(s)`} />
                      ) : (
                        <Badge variant="error" label="échec de connexion" />
                      )
                    ) : (
                      <Badge variant="neutral" label="désactivé" />
                    )}
                  </div>
                  <Text size="2xs" color="secondary" className="mt-1 block truncate">
                    {s.command} {s.args.join(" ")}
                  </Text>
                  {s.error && (
                    <Text size="2xs" className="mt-1 block text-error">
                      {s.error}
                    </Text>
                  )}
                  {s.connected && s.tools.length > 0 && (
                    <Text size="2xs" color="secondary" className="mt-1 block truncate">
                      {s.tools.join(", ")}
                    </Text>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    label="Activé"
                    isLabelHidden
                    value={s.enabled}
                    onChange={() => { void toggleServer(s); }}
                    size="sm"
                  />
                  <IconButton
                    label="Supprimer"
                    icon={<TrashIcon />}
                    variant="ghost"
                    size="sm"
                    onClick={() => { setDeletingName(s.name); }}
                  />
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      <AlertDialog
        isOpen={deletingName !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setDeletingName(null);
        }}
        title="Supprimer ce serveur MCP ?"
        description={`« ${deletingName ?? ""} » sera déconnecté et ses outils ne seront plus disponibles.`}
        actionLabel="Supprimer"
        onAction={confirmDelete}
      />
    </div>
  );
}
