import { useState } from "react";
import { Dialog } from "@astryxdesign/core/Dialog";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { open as openFolderDialog } from "@tauri-apps/plugin-dialog";
import { FolderIcon, XIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface Project {
  id: string;
  name: string;
  folder_path: string;
}

interface NewProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
  onCreated: (projects: Project[]) => void;
}

/** Modale de creation de projet, style Claude Desktop (titre, champ nom,
 * bouton dossier, Annuler/Creer) plutot que le formulaire replie dans la
 * sidebar - ferme au clic en dehors ou sur Echap comme SettingsModal. */
export function NewProjectModal({ isOpen, onClose, onCreated }: NewProjectModalProps) {
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  function reset() {
    setName("");
    setFolder("");
    setError(null);
    setCreating(false);
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function pickFolder() {
    const picked = await openFolderDialog({ directory: true, multiple: false });
    if (typeof picked === "string") setFolder(picked);
  }

  async function submit() {
    if (!name.trim() || !folder.trim()) {
      setError("le nom et le dossier sont obligatoires.");
      return;
    }
    setCreating(true);
    setError(null);

    try {
      const res = await fetch(`${API_BASE}/projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), folder_path: folder.trim() }),
      });

      if (!res.ok) {
        const body = (await res.json().catch(() => null)) as { detail?: string } | null;
        setError(body?.detail ?? `erreur ${res.status}`);
        return;
      }

      onCreated((await res.json()) as Project[]);
      handleClose();
    } catch {
      setError("impossible de contacter l'API Triton (127.0.0.1:8000).");
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
