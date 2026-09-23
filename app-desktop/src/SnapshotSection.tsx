import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { fetchSnapshotPoints, type SnapshotPoint } from "./snapshotDiff";

interface SnapshotSectionProps {
  sessionId: string | null;
  onOpenHistory: () => void;
}

/** Write safety net (see triton/tools/snapshot.py backend-side): a snapshot
 * is taken before the first write of each conversation turn (at most once
 * per turn), so a session that wrote across several turns has several
 * restore points. This banner now only signals their presence and opens the
 * real history browser (see SnapshotHistoryView.tsx, GitHub Desktop-style)
 * rather than offering fixed "last message"/"whole session" shortcuts -
 * restoring to any specific point now happens from that view. Not shown
 * until this session has written something. */
export function SnapshotSection({ sessionId, onOpenHistory }: SnapshotSectionProps) {
  const [points, setPoints] = useState<SnapshotPoint[]>([]);

  // no synchronous setPoints() call here (only inside the callback):
  // react-hooks (set-state-in-effect) forbids a synchronous setState in an
  // effect - same guard as McpSettings.tsx. Without a sessionId, the render
  // guard below (!sessionId || points.length === 0) already hides the
  // banner, no need to clear state here. Accepted consequence: on
  // sessionId change, an old list still in state can briefly stay shown
  // until the request answers, before being replaced.
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
      {/* vertical stack rather than one line: the side panel is too narrow
          for the sentence + button side by side without the text getting
          squeezed - see the conversation where the banner rendered as 3
          stacked "columns" in a narrow panel */}
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
