import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { fetchSnapshotPoints, type SnapshotPoint } from "./snapshotDiff";

interface SnapshotSectionProps {
  sessionId: string | null;
  onOpenHistory: () => void;
}

/** Filet de securite ecriture (voir triton/tools/snapshot.py cote backend) :
 * un instantane est pris avant la premiere ecriture de chaque tour de
 * conversation (pas plus qu'une fois par tour), donc une session qui a
 * ecrit dans plusieurs tours a plusieurs points de restauration. Ce bandeau
 * ne fait plus que signaler leur presence et ouvrir le vrai navigateur
 * d'historique (voir SnapshotHistoryView.tsx, style GitHub Desktop) plutot
 * que de proposer des raccourcis fixes "dernier message"/"toute la
 * session" - restaurer vers n'importe quel point precis se fait maintenant
 * depuis cette vue. Ne s'affiche pas tant qu'aucune ecriture n'a eu lieu
 * dans cette session. */
export function SnapshotSection({ sessionId, onOpenHistory }: SnapshotSectionProps) {
  const [points, setPoints] = useState<SnapshotPoint[]>([]);

  // pas d'appel synchrone a setPoints() ici (seulement dans le callback) :
  // react-hooks (set-state-in-effect) interdit setState synchrone dans un
  // effet - voir McpSettings.tsx pour le meme garde-fou. Sans sessionId,
  // la garde de rendu plus bas (!sessionId || points.length === 0) masque
  // deja le bandeau, pas besoin de vider l'etat ici. Consequence acceptee :
  // au changement de sessionId, une ancienne liste encore en etat peut
  // brievement rester affichee le temps que la requete reponde, avant
  // d'etre remplacee.
  useEffect(() => {
    if (!sessionId) return;
    void fetchSnapshotPoints(sessionId)
      .then(setPoints)
      .catch(() => {
        setPoints([]);
      });
  }, [sessionId]);

  if (!sessionId || points.length === 0) return null;

  return (
    <div className="border-b border-border px-2 py-2">
      {/* pile verticale plutot qu'une seule ligne : le panneau lateral est
          trop etroit pour la phrase + le bouton cote a cote sans que le
          texte se retrouve compresse - voir la conversation ou le bandeau
          s'affichait sur 3 "colonnes" superposees dans un panneau etroit */}
      <div className="flex flex-col gap-1.5 rounded-md px-2 py-1.5">
        <Text size="sm" color="secondary">
          {points.length} sauvegarde{points.length > 1 ? "s" : ""} interne
          {points.length > 1 ? "s" : ""} disponible{points.length > 1 ? "s" : ""}
        </Text>
        <div>
          <Button label="Voir l'historique" variant="ghost" size="sm" onClick={onOpenHistory}>
            Voir l'historique
          </Button>
        </div>
      </div>
    </div>
  );
}
