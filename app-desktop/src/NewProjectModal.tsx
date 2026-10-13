import { useState } from "react";
import { Dialog } from "@astryxdesign/core/Dialog";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { FolderIcon, XIcon } from "./icons";

import { API_BASE } from "./api";

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

interface NewProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (projects: Project[]) => void;
  isWebDeployment?: boolean;
}

/** Modale de creation de projet, style Claude Desktop (titre, champ nom,
 * bouton dossier, Annuler/Creer) plutot que le formulaire replie dans la
 * sidebar - ferme au clic en dehors ou sur Echap comme SettingsModal. */
export function NewProjectModal({
  isOpen,
  onClose,
  onCreated,
  isWebDeployment = false,
}: NewProjectModalProps) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [source, setSource] = useState<"empty" | "git" | "template">("empty");
  const [gitUrl, setGitUrl] = useState("");
  const [template, setTemplate] = useState("python");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function reset() {
    setName("");
    setFolder("");
    setSource("empty");
    setGitUrl("");
    setTemplate("python");
    setError(null);
    setCreating(false);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function pickFolder() {
    const { open: openFolderDialog } = await import("@tauri-apps/plugin-dialog");
    const picked = await openFolderDialog({ directory: true, multiple: false });
    if (typeof picked === "string") setFolder(picked);
  }

  async function submit() {
    if (!name.trim() || (!isWebDeployment && !folder.trim()) || (source === "git" && !gitUrl.trim())) {
      setError("le nom et le dossier sont obligatoires.");
      return;
    }
    setCreating(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          isWebDeployment
            ? {
                name: name.trim(),
                ...(source === "git" ? { git_url: gitUrl.trim() } : {}),
                ...(source === "template" ? { template } : {}),
              }
            : { name: name.trim(), folder_path: folder.trim() },
        ),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      onCreated((await res.json()) as Project[]);
      handleClose();
    } catch {
      setError("impossible de contacter l'API Triton.");
    } finally {
      setCreating(false);
    }
  }

  return (
    <Dialog
      isOpen={isOpen}
      onOpenChange={(open) => {
        if (!open) handleClose();
      }}
      purpose="info"
      width={480}
      aria-label="Créer un projet"
    >
      <div className="flex flex-col gap-5 p-6">
        <div className="flex items-start justify-between gap-3">
          <Text size="lg" weight="semibold">
            Créer un projet
          </Text>
          <IconButton
            label="Fermer"
            icon={<XIcon />}
            variant="ghost"
            size="sm"
            onClick={handleClose}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Text size="sm" weight="medium">
            Sur quoi travaillez-vous ?
          </Text>
          <TextInput
            value={name}
            onChange={setName}
            placeholder="Nommez votre projet"
            isLabelHidden
            label="Nom du projet"
            hasAutoFocus
          />
        </div>

        {isWebDeployment ? (
          <div className="flex flex-col gap-3">
            <Text size="sm" color="secondary">
              Un workspace isolé sera créé pour ce projet.
            </Text>
            <div className="flex gap-2" role="group" aria-label="Source du projet">
              {([
                ["empty", "Vide"],
                ["git", "Dépôt Git"],
                ["template", "Modèle"],
              ] as const).map(([value, label]) => (
                <Button
                  key={value}
                  label={label}
                  size="sm"
                  variant={source === value ? "primary" : "secondary"}
                  onClick={() => {
                    setSource(value);
                  }}
                />
              ))}
            </div>
            {source === "git" && (
              <TextInput
                value={gitUrl}
                onChange={setGitUrl}
                placeholder="https://github.com/organisation/projet.git"
                isLabelHidden
                label="URL du dépôt Git"
              />
            )}
            {source === "template" && (
              <label className="flex flex-col gap-1.5 text-sm font-medium">
                Modèle de projet
                <select
                  value={template}
                  onChange={(event) => {
                    setTemplate(event.target.value);
                  }}
                  className="rounded-md border border-border bg-surface px-3 py-2 text-sm"
                >
                  <option value="python">Python</option>
                  <option value="react">React</option>
                  <option value="api">API FastAPI</option>
                  <option value="discord-bot">Bot Discord</option>
                </select>
              </label>
            )}
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            <Text size="sm" weight="medium">
              Dossier de travail
            </Text>
            <Button
              label={folder || "Utiliser un dossier"}
              icon={<FolderIcon />}
              variant="secondary"
              onClick={() => {
                void pickFolder();
              }}
              className="justify-start truncate"
            />
          </div>
        )}

        {error && (
          <Text size="sm" className="text-error">
            {error}
          </Text>
        )}

        <div className="flex justify-end gap-2">
          <Button label="Annuler" variant="ghost" onClick={handleClose} />
          <Button
            label="Créer un projet"
            variant="primary"
            isLoading={creating}
            onClick={() => {
              void submit();
            }}
          />
        </div>
      </div>
    </Dialog>
  );
}
