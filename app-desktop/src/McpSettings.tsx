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
import { PencilIcon, PlugIcon, PlusIcon, TerminalIcon, TrashIcon } from "./icons";

import { API_BASE } from "./api";

interface McpServer {
  name: string;
  command: string;
  args: string[];
  enabled: boolean;
  connected: boolean;
  error: string | null;
  tools: string[];
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

/** Les arguments d'un serveur peuvent contenir un header Authorization ou une
 * clé passée en ligne de commande. L'aperçu doit rester utile sans exposer un
 * secret dans la modale. La configuration envoyée à l'API reste inchangée. */
function commandPreview(command: string, args: string[]): string {
  return `${command} ${args.join(" ")}`
    .replace(/(authorization:\s*bearer\s+)\S+/gi, "$1••••••••")
    .replace(/((?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+/gi, "$1••••••••");
}

export function McpSettings() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [editingName, setEditingName] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [deletingName, setDeletingName] = useState<string | null>(null);
  const [updatingName, setUpdatingName] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [envText, setEnvText] = useState("");

  // pas d'appel synchrone a setLoading() ici (seulement dans les callbacks) :
  // react-hooks (set-state-in-effect) interdit setState synchrone dans un
  // effet, et loading demarre deja a true via son useState initial.
  useEffect(() => {
    fetch(`${API_BASE}/mcp/servers`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: McpServer[]) => { setServers(data); })
      .catch(() => {
        setServers([]);
        setError("Impossible de charger les serveurs MCP.");
      })
      .finally(() => { setLoading(false); });
  }, []);

  function resetForm() {
    setName("");
    setCommand("");
    setArgsText("");
    setEnvText("");
    setFormError(null);
    setShowForm(false);
    setEditingName(null);
  }

  function startEdit(server: McpServer) {
    setName(server.name);
    setCommand(server.command);
    setArgsText(server.args.join("\n"));
    setEnvText("");
    setFormError(null);
    setEditingName(server.name);
    setShowForm(true);
  }

  async function submitForm() {
    if (!name.trim() || !command.trim()) {
      setFormError("le nom et la commande sont obligatoires.");
      return;
    }
    setSubmitting(true);
    setFormError(null);

    try {
      const currentServer = servers.find((s) => s.name === editingName);
      const res = await fetch(
        editingName ? `${API_BASE}/mcp/servers/${editingName}` : `${API_BASE}/mcp/servers`,
        {
          method: editingName ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: name.trim(),
            command: command.trim(),
            args: parseLines(argsText),
            env: parseEnv(envText),
            enabled: editingName ? (currentServer?.enabled ?? true) : true,
          }),
        },
      );

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setFormError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      const data = (await res.json()) as McpServer[];
      setServers(data);
      resetForm();
    } catch {
      setFormError("impossible de contacter l'API Triton.");
    } finally {
      setSubmitting(false);
    }
  }

  async function toggleServer(server: McpServer) {
    setUpdatingName(server.name);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/mcp/servers/${server.name}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: !server.enabled }),
      });
      if (!res.ok) throw new Error("MCP server update failed");
      setServers((await res.json()) as McpServer[]);
    } catch {
      setError(`Impossible de modifier « ${server.name} ».`);
    } finally {
      setUpdatingName(null);
    }
  }

  async function confirmDelete() {
    if (!deletingName) return;
    const nameToDelete = deletingName;
    setDeletingName(null);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/mcp/servers/${nameToDelete}`, { method: "DELETE" });
      if (!res.ok) throw new Error("MCP server deletion failed");
      setServers((await res.json()) as McpServer[]);
    } catch {
      setError(`Impossible de supprimer « ${nameToDelete} ».`);
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-start justify-between gap-4 pr-8">
        <div>
          <Text size="lg" weight="semibold" className="mb-1 block">
            Serveurs MCP
          </Text>
          <Text size="sm" color="secondary" className="block max-w-xl">
            Connecte des services externes pour donner au modèle de nouveaux outils, sans les
            intégrer directement au harness.
          </Text>
        </div>
        {!loading && servers.length > 0 && (
          <Badge
            variant="blue"
            label={`${servers.length} serveur${servers.length > 1 ? "s" : ""}`}
            className="shrink-0"
          />
        )}
      </div>

      <div className="mb-4 flex flex-col gap-3 rounded-xl bg-accent-muted px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-start gap-3">
          <div className="mt-0.5 shrink-0 text-accent">
            <PlugIcon className="h-4 w-4" />
          </div>
          <Text size="2xs" color="secondary">
            Même format que Claude Desktop : une commande, des arguments et, si besoin, des
            variables d'environnement. Les outils deviennent disponibles au prochain run.
          </Text>
        </div>
        {!showForm && (
          <Button
            label="Ajouter un serveur"
            icon={<PlusIcon />}
            variant="primary"
            size="sm"
            className="shrink-0"
            onClick={() => { setShowForm(true); }}
          />
        )}
      </div>

      {showForm && (
        <section className="mb-4 overflow-hidden rounded-2xl border border-accent bg-surface">
          <div className="flex items-center gap-3 border-b border-border bg-accent-muted px-4 py-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-surface text-accent">
              {editingName ? <PencilIcon className="h-5 w-5" /> : <PlusIcon className="h-5 w-5" />}
            </div>
            <div>
              <Text weight="semibold" className="block">
                {editingName ? `Modifier « ${editingName} »` : "Nouveau serveur MCP"}
              </Text>
              <Text size="2xs" color="secondary" className="block">
                {editingName
                  ? "Les champs sont pré-remplis, sauf les variables d'environnement."
                  : "La configuration est enregistrée puis le serveur est connecté."}
              </Text>
            </div>
          </div>
          <div className="p-4">
            <div className="mb-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
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
            <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
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
                placeholder={
                  editingName ? "laisser vide pour ne rien changer" : "API_KEY=..."
                }
              />
            </div>
            {formError && (
              <Text size="sm" className="mb-3 block text-error">
                {formError}
              </Text>
            )}
            <div className="flex items-center gap-2">
              <Button
                label={editingName ? "Enregistrer" : "Ajouter et connecter"}
                icon={editingName ? <PencilIcon /> : <PlugIcon />}
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

      {error && (
        <Text size="sm" className="mb-3 block text-error">
          {error}
        </Text>
      )}

      {loading && (
        <div className="flex flex-col gap-3" role="status" aria-label="Chargement des serveurs MCP">
          {[0, 1, 2].map((item) => (
            <div
              key={item}
              className="h-36 animate-pulse rounded-2xl border border-border bg-muted"
            />
          ))}
        </div>
      )}

      {!loading && servers.length === 0 && !showForm && !error ? (
        <EmptyState
          title="Aucun serveur MCP configuré"
          description="Ajoute un serveur pour donner au modèle des outils supplémentaires, sans avoir à les coder toi-même."
        />
      ) : !loading && servers.length > 0 ? (
        <div className="flex flex-col gap-3">
          {servers.map((s) => (
            <section
              key={s.name}
              className="rounded-2xl border border-border bg-surface px-4 py-3.5 transition-colors hover:border-accent"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 flex-1 items-start gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-muted text-accent">
                    <PlugIcon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 pt-0.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <Text weight="semibold">{s.name}</Text>
                      {s.enabled ? (
                        s.connected ? (
                          <Badge
                            variant="success"
                            label={`${s.tools.length} outil${s.tools.length > 1 ? "s" : ""}`}
                          />
                        ) : (
                          <Badge variant="error" label="connexion échouée" />
                        )
                      ) : (
                        <Badge variant="neutral" label="désactivé" />
                      )}
                    </div>
                    <Text size="2xs" color="secondary" className="mt-1 block">
                      {s.enabled
                        ? s.connected
                          ? "Connecté et prêt à fournir ses outils."
                          : "Le serveur est activé mais la connexion a échoué."
                        : "Ce serveur ne sera pas lancé lors des prochains runs."}
                    </Text>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Text size="2xs" color="secondary" className="hidden sm:block">
                    Activé
                  </Text>
                  <Switch
                    label={`Activer ${s.name}`}
                    isLabelHidden
                    value={s.enabled}
                    isDisabled={updatingName === s.name}
                    onChange={() => { void toggleServer(s); }}
                    size="sm"
                  />
                  <IconButton
                    label="Modifier"
                    icon={<PencilIcon />}
                    variant="ghost"
                    size="sm"
                    isDisabled={updatingName === s.name}
                    onClick={() => { startEdit(s); }}
                  />
                  <IconButton
                    label="Supprimer"
                    icon={<TrashIcon />}
                    variant="ghost"
                    size="sm"
                    isDisabled={updatingName === s.name}
                    onClick={() => { setDeletingName(s.name); }}
                  />
                </div>
              </div>

              <div className="mt-3 rounded-xl bg-muted px-3 py-2.5">
                <div className="mb-1 flex items-center gap-2 text-secondary">
                  <TerminalIcon className="h-3.5 w-3.5" />
                  <Text size="2xs" color="secondary" className="uppercase tracking-wide">
                    Commande
                  </Text>
                </div>
                <code className="block truncate font-mono text-[11px] text-secondary">
                  {commandPreview(s.command, s.args)}
                </code>
              </div>

              {s.error && (
                <Text size="2xs" className="mt-2 block rounded-lg bg-error-muted px-3 py-2 text-error">
                  {s.error}
                </Text>
              )}
              {s.connected && s.tools.length > 0 && (
                <div className="mt-3">
                  <Text size="2xs" color="secondary" className="mb-1 block uppercase tracking-wide">
                    Outils disponibles
                  </Text>
                  <Text size="2xs" color="secondary" className="block truncate font-mono">
                    {s.tools.join(" · ")}
                  </Text>
                </div>
              )}
            </section>
          ))}
        </div>
      ) : null}

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
