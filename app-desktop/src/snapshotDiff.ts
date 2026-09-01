const API_BASE = "http://127.0.0.1:8000";

export interface SnapshotDiff {
  created: string[];
  deleted: string[];
  modified: string[];
}

/** GET /sessions/{id}/snapshot/diff - what restoring this session's
 * snapshot would actually change. Used to enrich the restore
 * confirmation (see SnapshotSection.tsx and App.tsx's /undo flow) right
 * before the user commits to it - null on any failure (no snapshot,
 * project deleted, ...), the confirmation still works without it, just
 * without the extra detail. */
export async function fetchSnapshotDiff(sessionId: string): Promise<SnapshotDiff | null> {
  try {
    const r = await fetch(`${API_BASE}/sessions/${sessionId}/snapshot/diff`);
    if (!r.ok) return null;
    return (await r.json()) as SnapshotDiff;
  } catch {
    return null;
  }
}

const MAX_NAMES_SHOWN = 6;

/** A plain-text summary of a snapshot diff, meant to be appended to
 * AlertDialog's `description` (a plain string, no rich content slot) so
 * the restore confirmation says what will actually happen - which files
 * get removed (created since the snapshot), brought back (deleted
 * since), or reverted (modified since) - instead of only a generic
 * "this is irreversible" warning. Returns "" while the diff hasn't
 * loaded yet or failed to, so the base description reads fine on its
 * own either way. */
export function describeSnapshotDiff(diff: SnapshotDiff | null): string {
  if (!diff) return "";
  const total = diff.created.length + diff.deleted.length + diff.modified.length;
  if (total === 0) return " Aucun changement détecté depuis l'instantané.";

  const parts: string[] = [];
  if (diff.modified.length > 0) parts.push(`${diff.modified.length} modifié(s)`);
  if (diff.created.length > 0) parts.push(`${diff.created.length} créé(s) (seront supprimés)`);
  if (diff.deleted.length > 0) parts.push(`${diff.deleted.length} supprimé(s) (seront recréés)`);

  const names = [...diff.modified, ...diff.created, ...diff.deleted];
  const shown = names.slice(0, MAX_NAMES_SHOWN).join(", ");
  const remaining = names.length - MAX_NAMES_SHOWN;
  const more = remaining > 0 ? ` et ${remaining} autre(s)` : "";

  return ` ${parts.join(", ")} : ${shown}${more}.`;
}
