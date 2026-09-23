import { API_BASE } from "./api";

export interface SnapshotPoint {
  turn_index: number;
  // "content" (the current homemade content-addressable store, used for
  // every project - see triton/tools/snapshot.py) or a legacy "git"/
  // "copy" value from a snapshot taken before that existed. Not used for
  // any rendering decision here - kept as a plain string rather than a
  // literal union so this file doesn't need to track the backend's
  // internal storage format.
  kind: string;
  created_at: string;
  message_preview: string | null;
  // absent in fixtures and older servers; false means an old "before write"
  // point, true an internal before/after commit.
  has_final_state?: boolean;
}

export type SnapshotView = "rollback" | "commit";

export class SnapshotRequestError extends Error {}

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new SnapshotRequestError(`La sauvegarde n'a pas pu être chargée (${response.status}).`);
  }
  return (await response.json()) as T;
}

export interface SnapshotDiff {
  created: string[];
  deleted: string[];
  modified: string[];
}

/** GET /sessions/{id}/snapshots - every restore point this session has
 * (one per turn whose first write triggered a snapshot, oldest first) -
 * empty when there's none, never a 404. Used by SnapshotSection.tsx (the
 * file panel banner) and App.tsx's /undo command to decide whether to
 * offer a restore action at all, and which turn(s) to offer. */
export async function fetchSnapshotPoints(
  sessionId: string,
  signal?: AbortSignal,
): Promise<SnapshotPoint[]> {
  return requestJson<SnapshotPoint[]>(`${API_BASE}/sessions/${sessionId}/snapshots`, signal);
}

/** GET /sessions/{id}/snapshot/diff?turn_index=N - what restoring to
 * that specific turn's snapshot would actually change. Used to enrich
 * the restore confirmation right before the user commits to it - null
 * on any failure (no snapshot for that turn, project deleted, ...), the
 * confirmation still works without it, just without the extra detail. */
export async function fetchSnapshotDiff(
  sessionId: string,
  turnIndex: number,
  view: SnapshotView = "rollback",
  signal?: AbortSignal,
): Promise<SnapshotDiff> {
  return requestJson<SnapshotDiff>(
    `${API_BASE}/sessions/${sessionId}/snapshot/diff?turn_index=${turnIndex}&view=${view}`,
    signal,
  );
}

export interface SnapshotFileContent {
  old: string | null;
  new: string | null;
}

/** GET /sessions/{id}/snapshot/file?turn_index=N&path=... - the before/
 * after text content of one changed file, for the restore-history
 * browser's diff pane (see SnapshotHistoryView.tsx). `old`/`new` are
 * null when the path didn't exist at that point in time (a created or
 * deleted file respectively) - null on any failure too (no snapshot for
 * that turn, project deleted...), same "fail soft" convention as
 * fetchSnapshotDiff. */
export async function fetchSnapshotFileContent(
  sessionId: string,
  turnIndex: number,
  path: string,
  view: SnapshotView = "rollback",
  signal?: AbortSignal,
): Promise<SnapshotFileContent> {
  return requestJson<SnapshotFileContent>(
    `${API_BASE}/sessions/${sessionId}/snapshot/file` +
      `?turn_index=${turnIndex}&path=${encodeURIComponent(path)}&view=${view}`,
    signal,
  );
}

export type SnapshotFileChangeType = "created" | "deleted" | "modified";

export interface SnapshotChangedFile {
  path: string;
  type: SnapshotFileChangeType;
}

/** Flattens a SnapshotDiff's three separate arrays into one sorted list
 * with each path's change type attached - what the restore-history
 * browser's "changed files" column actually renders (one row per file,
 * badge colored by type), rather than three separate loops. */
export function changedFiles(diff: SnapshotDiff): SnapshotChangedFile[] {
  return [
    ...diff.created.map((path) => ({ path, type: "created" as const })),
    ...diff.deleted.map((path) => ({ path, type: "deleted" as const })),
    ...diff.modified.map((path) => ({ path, type: "modified" as const })),
  ].sort((a, b) => a.path.localeCompare(b.path));
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
