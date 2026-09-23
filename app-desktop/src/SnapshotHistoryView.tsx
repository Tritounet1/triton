import { useEffect, useState } from "react";
import { AlertDialog } from "@astryxdesign/core/AlertDialog";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { Timestamp } from "@astryxdesign/core/Timestamp";
import { ArrowLeftIcon, ClockIcon } from "./icons";
import {
  changedFiles,
  describeSnapshotDiff,
  fetchSnapshotDiff,
  fetchSnapshotFileContent,
  fetchSnapshotPoints,
  type SnapshotChangedFile,
  type SnapshotDiff,
  type SnapshotFileChangeType,
  type SnapshotFileContent,
  type SnapshotPoint,
  type SnapshotView,
} from "./snapshotDiff";

import { API_BASE } from "./api";

function changeBadgeVariant(type: SnapshotFileChangeType): "success" | "warning" | "error" {
  if (type === "created") return "success";
  if (type === "deleted") return "error";
  return "warning";
}

function changeBadgeLetter(type: SnapshotFileChangeType): string {
  if (type === "created") return "A";
  if (type === "deleted") return "D";
  return "M";
}

/** Same rendering as App.tsx's EditFileDiff (all old content in red, all new
 * in green - no fine-grained line-by-line diff), applied here to a whole
 * file rather than a single edit_file hunk, and without the confirmation
 * version's height cap (max-h-64) since this panel is dedicated to it. */
function SnapshotFileDiff({ content }: { content: SnapshotFileContent }) {
  const { old, new: current } = content;
  if (old === null && current === null) {
    return (
      <div className="p-6">
        <Text size="sm" color="secondary">
          Contenu introuvable pour ce fichier.
        </Text>
      </div>
    );
  }
  return (
    <div className="font-mono text-xs">
      {old
        ?.split("\n")
        .map((line, i) => (
          <div
            key={`old-${i}`}
            className="whitespace-pre bg-error-muted px-4 py-0.5 text-error"
          >
            <span className="select-none opacity-60">- </span>
            {line}
          </div>
        ))}
      {current
        ?.split("\n")
        .map((line, i) => (
          <div
            key={`new-${i}`}
            className="whitespace-pre bg-success-muted px-4 py-0.5 text-success"
          >
            <span className="select-none opacity-60">+ </span>
            {line}
          </div>
        ))}
    </div>
  );
}

interface SnapshotHistoryViewProps {
  sessionId: string;
  onBack: () => void;
  /** Called after a successful restore, so the parent reloads the displayed
   * file tree (its content may have changed under it) - same contract as
   * SnapshotSection.tsx before it. */
  onRestored: () => void;
}

/** Full-screen view (replaces the conversation, SideNav stays - see
 * App.tsx's `view`) GitHub Desktop-style for the safety net: a column of
 * "commits" (one per turn that wrote something), the files changed for the
 * selected turn, and the selected file's before/after content - replaces
 * SnapshotSection.tsx's two "last message"/"whole session" shortcuts with a
 * real rollback to any point (already supported API-side - see server.py's
 * POST .../snapshot/restore). */
export function SnapshotHistoryView({ sessionId, onBack, onRestored }: SnapshotHistoryViewProps) {
  const [points, setPoints] = useState<SnapshotPoint[]>([]);
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);
  const [diffTurn, setDiffTurn] = useState<number | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<SnapshotFileContent | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [loadingPoints, setLoadingPoints] = useState(true);
  const [loadingDiff, setLoadingDiff] = useState(false);
  const [loadingContent, setLoadingContent] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [restoreError, setRestoreError] = useState<string | null>(null);

  const selectedPoint = points.find((p) => p.turn_index === selectedTurn) ?? null;
  const selectedView: SnapshotView =
    selectedPoint?.has_final_state === true ? "commit" : "rollback";

  // loads the restore-point list on open, and selects the most recent one
  // by default (like GitHub Desktop's already-selected latest commit).
  useEffect(() => {
    const controller = new AbortController();
    void fetchSnapshotPoints(sessionId, controller.signal)
      .then((loaded) => {
        if (controller.signal.aborted) return;
        setPoints(loaded);
        setSelectedTurn(loaded[loaded.length - 1]?.turn_index ?? null);
        setLoadingDiff(loaded.length > 0);
        setLoadError(null);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setPoints([]);
          setSelectedTurn(null);
          setLoadError("Impossible de charger l'historique des sauvegardes.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingPoints(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [sessionId]);

  // reloads the changed-files list whenever the selected turn changes, and
  // selects the first file by default. No synchronous reset to null here
  // when selectedTurn is already null (not allowed in an effect - same
  // guard as McpSettings.tsx): that case only happens when the session has
  // no restore point, or briefly before the first load, and the render
  // below only relies on `diff`/`selectedPath` once they're actually
  // populated anyway.
  useEffect(() => {
    const controller = new AbortController();
    if (selectedTurn === null) {
      return () => {
        controller.abort();
      };
    }

    void fetchSnapshotDiff(sessionId, selectedTurn, selectedView, controller.signal)
      .then((loaded) => {
        if (controller.signal.aborted) return;
        setDiff(loaded);
        setDiffTurn(selectedTurn);
        setSelectedPath(changedFiles(loaded)[0]?.path ?? null);
        setContent(null);
        setLoadingContent(changedFiles(loaded).length > 0);
        setLoadError(null);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLoadError("Impossible de charger les changements de cette sauvegarde.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingDiff(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [sessionId, selectedTurn, selectedView]);

  // reloads before/after content whenever the selected file or turn
  // changes - same guard as above.
  useEffect(() => {
    const controller = new AbortController();
    if (selectedTurn === null || selectedPath === null) {
      return () => {
        controller.abort();
      };
    }

    void fetchSnapshotFileContent(
      sessionId,
      selectedTurn,
      selectedPath,
      selectedView,
      controller.signal,
    )
      .then((loaded) => {
        if (!controller.signal.aborted) {
          setContent(loaded);
          setLoadError(null);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setLoadError("Impossible de charger le contenu de ce fichier.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoadingContent(false);
        }
      });
    return () => {
      controller.abort();
    };
  }, [sessionId, selectedTurn, selectedPath, selectedView]);

  async function restore() {
    if (selectedTurn === null) return;
    setRestoring(true);
    setRestoreError(null);
    try {
      const response = await fetch(`${API_BASE}/sessions/${sessionId}/snapshot/restore`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn_index: selectedTurn, state: selectedView === "commit" ? "after" : "before" }),
      });
      if (!response.ok) throw new Error("restore failed");
      setConfirmOpen(false);
      onRestored();
    } catch {
      setRestoreError("La restauration a échoué. Les fichiers n'ont pas été confirmés comme restaurés.");
    } finally {
      setRestoring(false);
    }
  }

  // most recent first, like GitHub Desktop's commit list -
  // fetchSnapshotPoints returns oldest first (see its docstring).
  const orderedPoints = [...points].reverse();
  const displayedDiff = diffTurn === selectedTurn ? diff : null;
  const files: SnapshotChangedFile[] = displayedDiff ? changedFiles(displayedDiff) : [];

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-border px-4 py-3">
        <IconButton
          label="Retour"
          icon={<ArrowLeftIcon />}
          variant="ghost"
          size="sm"
          onClick={onBack}
        />
        <ClockIcon className="h-5 w-5 shrink-0 text-secondary" />
        <Text size="lg" weight="semibold">
          Historique des sauvegardes
        </Text>
        <Text size="sm" color="secondary" className="hidden sm:block">
          États internes du projet, sans modifier Git.
        </Text>
      </div>

      {loadError && (
        <div className="border-b border-error/30 bg-error-muted px-4 py-2">
          <Text size="sm" className="text-error">
            {loadError}
          </Text>
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        <div className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-border">
          {orderedPoints.length === 0 && (
            <div className="p-4">
              <EmptyState
                title={loadingPoints ? "Chargement…" : "Aucune sauvegarde"}
                description={
                  loadingPoints
                    ? "Les états internes du projet sont en cours de chargement."
                    : "Une sauvegarde est créée lorsqu'un message modifie le projet."
                }
              />
            </div>
          )}
          {orderedPoints.map((p) => (
            <button
              key={p.turn_index}
              onClick={() => {
                setSelectedTurn(p.turn_index);
                setSelectedPath(null);
                setContent(null);
                setLoadingDiff(true);
                setLoadingContent(false);
                setLoadError(null);
              }}
              className={`flex flex-col items-start gap-0.5 border-b border-border px-3 py-2.5 text-left ${
                p.turn_index === selectedTurn ? "bg-accent-muted" : "hover:bg-muted"
              }`}
            >
              <Text size="sm" weight="medium" className="line-clamp-2">
                {p.message_preview ?? `Tour ${p.turn_index}`}
              </Text>
              <div className="flex items-center gap-2">
                <Badge
                  variant={p.has_final_state === true ? "success" : "warning"}
                  label={p.has_final_state === true ? "État final" : "Point antérieur"}
                />
                <Timestamp value={new Date(p.created_at).getTime() / 1000} format="relative" />
              </div>
            </button>
          ))}
        </div>

        <div className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-border">
          <div className="border-b border-border px-3 py-2">
            <Text size="2xs" color="secondary">
              {files.length} fichier{files.length > 1 ? "s" : ""} modifié
              {files.length > 1 ? "s" : ""}
            </Text>
          </div>
          {files.map((f) => (
            <button
              key={f.path}
              onClick={() => {
                if (f.path === selectedPath) return;
                setSelectedPath(f.path);
                setContent(null);
                setLoadingContent(true);
                setLoadError(null);
              }}
              className={`flex items-center gap-2 border-b border-border px-3 py-2 text-left ${
                f.path === selectedPath ? "bg-accent-muted" : "hover:bg-muted"
              }`}
            >
              <Badge variant={changeBadgeVariant(f.type)} label={changeBadgeLetter(f.type)} />
              <Text size="2xs" className="min-w-0 flex-1 truncate font-mono">
                {f.path}
              </Text>
            </button>
          ))}
          {loadingDiff && (
            <div className="px-3 py-4">
              <Text size="sm" color="secondary">
                Chargement des changements…
              </Text>
            </div>
          )}
          {displayedDiff && files.length === 0 && !loadingDiff && (
            <div className="px-3 py-4">
              <Text size="sm" color="secondary">
                Aucun changement pour ce tour.
              </Text>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1 overflow-y-auto">
          {loadingContent && (
            <div className="p-6">
              <Text size="sm" color="secondary">
                Chargement du fichier…
              </Text>
            </div>
          )}
          {!loadingContent && selectedPath && content ? (
            <SnapshotFileDiff content={content} />
          ) : (
            !loadingContent && (
              <div className="p-6">
                <EmptyState
                  title="Sélectionnez un fichier"
                  description="Choisissez un fichier modifié pour voir son contenu avant/après."
                />
              </div>
            )
          )}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
        <Button
          label="Recharger cet état"
          variant="primary"
          isDisabled={selectedTurn === null || loadingDiff || loadError !== null}
          onClick={() => {
            setConfirmOpen(true);
          }}
        />
      </div>

      <AlertDialog
        isOpen={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Recharger cet état ?"
        description={`Le projet reviendra à l'état ${
          selectedView === "commit" ? "obtenu après" : "antérieur à"
        } « ${selectedPoint?.message_preview ?? "ce tour"} ». Cette action est irréversible.${describeSnapshotDiff(displayedDiff)}`}
        actionLabel="Recharger"
        isActionLoading={restoring}
        onAction={restore}
      />
      {restoreError && (
        <div className="border-t border-error/30 bg-error-muted px-4 py-2">
          <Text size="sm" className="text-error">
            {restoreError}
          </Text>
        </div>
      )}
    </div>
  );
}
