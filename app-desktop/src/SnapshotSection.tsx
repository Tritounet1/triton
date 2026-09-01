import { useEffect, useState } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import {
  describeSnapshotDiff,
  fetchSnapshotDiff,
  fetchSnapshotPoints,
  type SnapshotDiff,
  type SnapshotPoint,
} from "./snapshotDiff";

const API_BASE = "http://127.0.0.1:8000";

interface SnapshotSectionProps {
  sessionId: string | null;
  /** Appelee apres une restauration reussie, pour que le parent recharge
   * l'arbre de fichiers affiche (son contenu a pu changer sous ses pieds). */
  onRestored: () => void;
}

/** Filet de securite ecriture (voir triton/tools/snapshot.py cote backend) :
 * un instantane est pris avant la premiere ecriture de chaque tour de
 * conversation (pas plus qu'une fois par tour), donc une session qui a
 * ecrit dans plusieurs tours a plusieurs points de restauration - ce
 * bandeau propose "annuler le dernier message" en plus de "annuler toute
 * la session" quand il y en a plus d'un, ou un simple "Restaurer" s'il
 * n'y en a qu'un. Ne s'affiche pas tant qu'aucune ecriture n'a eu lieu
 * dans cette session. */
export function SnapshotSection({ sessionId, onRestored }: SnapshotSectionProps) {
  const [points, setPoints] = useState<SnapshotPoint[]>([]);
  const [restoreTarget, setRestoreTarget] = useState<SnapshotPoint | null>(null);
  const [restoring, setRestoring] = useState(false);
  // charge en arriere-plan des l'ouverture de la confirmation, pas au
  // montage du composant : c'est un vrai travail cote serveur (git diff,
  // ou lire le contenu de chaque fichier partage pour le backend non-git)
  // qui n'a de sens que juste avant que l'utilisateur ne s'engage vraiment.
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);

  // pas d'appel synchrone a setPoints() ici (seulement dans les
  // callbacks) : react-hooks (set-state-in-effect) interdit setState
  // synchrone dans un effet - voir McpSettings.tsx pour le meme
  // garde-fou. Sans sessionId, la garde de rendu plus bas (!sessionId ||
  // points.length === 0) masque deja le bandeau, pas besoin de vider
  // l'etat ici. Consequence acceptee : au changement de sessionId, une
  // ancienne liste encore en etat peut brievement rester affichee le
  // temps que la requete reponde, avant d'etre remplacee.
  useEffect(() => {
    if (!sessionId) return;
    void fetchSnapshotPoints(sessionId).then(setPoints);
  }, [sessionId]);

  function openConfirm(target: SnapshotPoint) {
    setDiff(null);
    setRestoreTarget(target);
    if (sessionId) {
      void fetchSnapshotDiff(sessionId, target.turn_index).then(setDiff);
    }
  }

  async function restore() {
    if (!sessionId || !restoreTarget) return;
    setRestoring(true);
    try {
      const r = await fetch(`${API_BASE}/sessions/${sessionId}/snapshot/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn_index: restoreTarget.turn_index }),
      });
      if (r.ok) {
        setRestoreTarget(null);
        onRestored();
      }
    } finally {
      setRestoring(false);
    }
  }

  if (!sessionId || points.length === 0) return null;

  const oldest = points[0];
  const newest = points[points.length - 1];
  // both guaranteed defined by points.length === 0 already returning
  // above - narrows for TS's noUncheckedIndexedAccess without a
  // non-null assertion (forbidden by this project's eslint config)
  if (!oldest || !newest) return null;
  const hasMultiplePoints = oldest.turn_index !== newest.turn_index;

  return (
    <>
      <div className="border-b border-border px-2 py-2">
        <div className="flex items-center gap-2 rounded-md px-2 py-1.5">
          <Text size="sm" color="secondary" className="min-w-0 flex-1">
            Filet de sécurité actif pour cette session
          </Text>
          {hasMultiplePoints ? (
            <>
              <Button
                label="Annuler le dernier message"
                variant="ghost"
                size="sm"
                onClick={() => {
                  openConfirm(newest);
                }}
              >
                Dernier message
              </Button>
              <Button
                label="Annuler toute la session"
                variant="ghost"
                size="sm"
                onClick={() => {
                  openConfirm(oldest);
                }}
              >
                Toute la session
              </Button>
            </>
          ) : (
            <Button
              label="Restaurer"
              variant="ghost"
              size="sm"
              onClick={() => {
                openConfirm(oldest);
              }}
            >
              Restaurer
            </Button>
          )}
        </div>
      </div>

      <AlertDialog
        isOpen={restoreTarget !== null}
        onOpenChange={(isOpen) => {
          if (!isOpen) setRestoreTarget(null);
        }}
        title={
          restoreTarget?.turn_index === oldest.turn_index
            ? "Restaurer l'état d'avant cette session ?"
            : "Annuler le dernier message ?"
        }
        description={`${
          restoreTarget?.turn_index === oldest.turn_index
            ? "Annule tous les fichiers créés, modifiés ou supprimés par cette conversation dans le dossier du projet, en revenant à l'état capturé juste avant sa première écriture."
            : "Annule les fichiers créés, modifiés ou supprimés depuis le dernier message écrit dans le dossier du projet."
        } Cette action est irréversible.${describeSnapshotDiff(diff)}`}
        actionLabel="Restaurer"
        isActionLoading={restoring}
        onAction={() => {
          void restore();
        }}
      />
    </>
  );
}
