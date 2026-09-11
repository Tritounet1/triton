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
} from "./snapshotDiff";

const API_BASE = "http://127.0.0.1:8000";

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

/** Meme rendu que App.tsx's EditFileDiff (tout l'ancien contenu en rouge,
 * tout le nouveau en vert - pas de diff ligne a ligne fine), applique ici
 * a un fichier entier plutot qu'a un seul hunk edit_file, et sans la
 * limite de hauteur (max-h-64) de la version confirmation puisque ce
 * panneau lui est dedie. */
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
  /** Appelee apres une restauration reussie, pour que le parent recharge
   * l'arbre de fichiers affiche (son contenu a pu changer sous ses pieds) -
   * meme contrat que SnapshotSection.tsx avant elle. */
  onRestored: () => void;
}

/** Vue plein ecran (remplace la conversation, la SideNav reste - voir
 * App.tsx's `view`) façon GitHub Desktop pour le filet de securite : une
 * colonne de "commits" (un par tour qui a ecrit quelque chose), les
 * fichiers changes pour le tour selectionne, et le contenu avant/apres du
 * fichier selectionne - remplace les deux raccourcis "dernier message"/
 * "toute la session" de SnapshotSection.tsx par un vrai retour en arriere
 * vers n'importe quel point (deja supporte cote API - voir
 * server.py's POST .../snapshot/restore). */
export function SnapshotHistoryView({ sessionId, onBack, onRestored }: SnapshotHistoryViewProps) {
  const [points, setPoints] = useState<SnapshotPoint[]>([]);
  const [selectedTurn, setSelectedTurn] = useState<number | null>(null);
  const [diff, setDiff] = useState<SnapshotDiff | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [content, setContent] = useState<SnapshotFileContent | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [restoring, setRestoring] = useState(false);

  // charge la liste des points de restauration a l'ouverture, et
  // selectionne le plus recent par defaut (comme le commit le plus recent
  // deja selectionne dans GitHub Desktop).
  useEffect(() => {
    void fetchSnapshotPoints(sessionId).then((loaded) => {
      setPoints(loaded);
      setSelectedTurn(loaded[loaded.length - 1]?.turn_index ?? null);
    });
  }, [sessionId]);

  // recharge la liste des fichiers changes des que le tour selectionne
  // change, et selectionne le premier fichier par defaut. Pas de reset
  // synchrone a null ici quand selectedTurn est deja null (interdit dans
  // un effet - voir McpSettings.tsx pour le meme garde-fou) : ce cas
  // n'arrive que quand la session n'a aucun point de restauration, ou
  // brievement avant le premier chargement, et le rendu plus bas ne
  // s'appuie de toute facon que sur `diff`/`selectedPath` une fois
  // reellement peuples.
  useEffect(() => {
    if (selectedTurn === null) return;
    void fetchSnapshotDiff(sessionId, selectedTurn).then((loaded) => {
      setDiff(loaded);
      setSelectedPath(loaded ? (changedFiles(loaded)[0]?.path ?? null) : null);
    });
  }, [sessionId, selectedTurn]);

  // recharge le contenu avant/apres des que le fichier ou le tour
  // selectionne change - meme garde-fou que ci-dessus.
  useEffect(() => {
    if (selectedTurn === null || selectedPath === null) return;
    void fetchSnapshotFileContent(sessionId, selectedTurn, selectedPath).then(setContent);
  }, [sessionId, selectedTurn, selectedPath]);

  function restore() {
    if (selectedTurn === null) return;
    setRestoring(true);
    void fetch(`${API_BASE}/sessions/${sessionId}/snapshot/restore`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ turn_index: selectedTurn }),
    })
      .then((r) => {
        if (r.ok) {
          setConfirmOpen(false);
          onRestored();
        }
      })
      .finally(() => {
        setRestoring(false);
      });
  }

  // le plus recent en tete, comme la liste de commits de GitHub Desktop -
  // fetchSnapshotPoints renvoie le plus ancien en tete (voir sa docstring).
  const orderedPoints = [...points].reverse();
  const selectedPoint = points.find((p) => p.turn_index === selectedTurn) ?? null;
  const files: SnapshotChangedFile[] = diff ? changedFiles(diff) : [];

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
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex w-64 shrink-0 flex-col overflow-y-auto border-r border-border">
          {orderedPoints.length === 0 && (
            <div className="p-4">
              <EmptyState
                title="Aucun point de restauration"
                description="Rien n'a encore été écrit dans cette conversation."
              />
            </div>
          )}
          {orderedPoints.map((p) => (
            <button
              key={p.turn_index}
              onClick={() => {
                setSelectedTurn(p.turn_index);
              }}
              className={`flex flex-col items-start gap-0.5 border-b border-border px-3 py-2.5 text-left ${
                p.turn_index === selectedTurn ? "bg-accent-muted" : "hover:bg-muted"
              }`}
            >
              <Text size="sm" weight="medium" className="line-clamp-2">
                {p.message_preview ?? `Tour ${p.turn_index}`}
              </Text>
              <Timestamp value={new Date(p.created_at).getTime() / 1000} format="relative" />
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
                setSelectedPath(f.path);
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
          {diff && files.length === 0 && (
            <div className="px-3 py-4">
              <Text size="sm" color="secondary">
                Aucun changement pour ce tour.
              </Text>
            </div>
          )}
        </div>

        <div className="min-w-0 flex-1 overflow-y-auto">
          {selectedPath && content ? (
            <SnapshotFileDiff content={content} />
          ) : (
            <div className="p-6">
              <EmptyState
                title="Sélectionnez un fichier"
                description="Choisissez un fichier modifié pour voir son contenu avant/après."
              />
            </div>
          )}
        </div>
      </div>

      <div className="flex items-center justify-end gap-2 border-t border-border px-4 py-3">
        <Button
          label="Restaurer à ce point"
          variant="primary"
          isDisabled={selectedTurn === null}
          onClick={() => {
            setConfirmOpen(true);
          }}
        />
      </div>

      <AlertDialog
        isOpen={confirmOpen}
        onOpenChange={setConfirmOpen}
        title="Restaurer à cet état ?"
        description={`Annule tous les fichiers créés, modifiés ou supprimés depuis « ${
          selectedPoint?.message_preview ?? "ce tour"
        } ». Cette action est irréversible.${describeSnapshotDiff(diff)}`}
        actionLabel="Restaurer"
        isActionLoading={restoring}
        onAction={restore}
      />
    </div>
  );
}
