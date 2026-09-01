import { useEffect, useState } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { describeSnapshotDiff, fetchSnapshotDiff, type SnapshotDiff } from "./snapshotDiff";

const API_BASE = "http://127.0.0.1:8000";

interface SnapshotInfo {
  kind: "git" | "copy";
  created_at: string;
}

interface SnapshotSectionProps {
  sessionId: string | null;
  /** Appelee apres une restauration reussie, pour que le parent recharge
   * l'arbre de fichiers affiche (son contenu a pu changer sous ses pieds). */
  onRestored: () => void;
}

/** Filet de securite ecriture (voir triton/tools/snapshot.py cote backend) :
 * si cette session a deja ecrit dans le projet, un instantane du dossier a
 * ete pris juste avant sa toute premiere ecriture - ce bandeau permet d'y
 * revenir en un clic, derriere une confirmation (action irreversible). Ne
 * s'affiche pas tant qu'aucune ecriture n'a eu lieu dans cette session. */
export function SnapshotSection({ sessionId, onRestored }: SnapshotSectionProps) {
  const [snapshot, setSnapshot] = useState<SnapshotInfo | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  // charge en arriere-plan des l'ouverture de la confirmation, pas au
  // montage du composant : c'est un vrai travail cote serveur (git diff,
  // ou lire le contenu de chaque fichier partage pour le backend non-git)
  // qui n'a de sens que juste avant que l'utilisateur ne s'engage vraiment.
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);

  // pas d'appel synchrone a setSnapshot() ici (seulement dans les
  // callbacks) : react-hooks (set-state-in-effect) interdit setState
  // synchrone dans un effet - voir McpSettings.tsx pour le meme
  // garde-fou. Sans sessionId, la garde de rendu plus bas (!sessionId ||
  // !snapshot) masque deja le bandeau, pas besoin de vider l'etat ici.
  // Consequence acceptee : au changement de sessionId, un ancien snapshot
  // encore en etat peut brievement rester affiche le temps que la requete
  // reponde, avant d'etre remplace ou retire par le .then()/.catch().
  useEffect(() => {
    if (!sessionId) return;
    fetch(`${API_BASE}/sessions/${sessionId}/snapshot`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: SnapshotInfo) => {
        setSnapshot(data);
      })
      .catch(() => {
        setSnapshot(null);
      });
  }, [sessionId]);

  async function restore() {
    setRestoring(true);
    try {
      const r = await fetch(`${API_BASE}/sessions/${sessionId}/snapshot/restore`, {
        method: "POST",
      });
      if (r.ok) {
        setConfirmOpen(false);
        onRestored();
      }
    } finally {
      setRestoring(false);
    }
  }

  if (!sessionId || !snapshot) return null;

  return (
    <>
      <div className="border-b border-border px-2 py-2">
        <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
          <Text size="sm" color="secondary" className="min-w-0 flex-1">
            Filet de sécurité actif pour cette session
          </Text>
          <Button
            label="Restaurer"
            variant="ghost"
            size="sm"
            onClick={() => {
              setDiff(null);
              setConfirmOpen(true);
              void fetchSnapshotDiff(sessionId).then(setDiff);
            }}
          >
            Restaurer
          </Button>
        </div>
      </div>

      <AlertDialog
        isOpen={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Restaurer l'état d'avant cette session ?"
        description={`Annule tous les fichiers créés, modifiés ou supprimés par cette conversation dans le dossier du projet, en revenant à l'état capturé juste avant sa première écriture. Cette action est irréversible.${describeSnapshotDiff(diff)}`}
        actionLabel="Restaurer"
        isActionLoading={restoring}
        onAction={() => {
          void restore();
        }}
      />
    </>
  );
}
