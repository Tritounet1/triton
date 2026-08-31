import { useEffect, useState } from "react";
import { openPath } from "@tauri-apps/plugin-opener";
import { TreeList, type TreeListItemData } from "@astryxdesign/core/TreeList";
import { Text } from "@astryxdesign/core/Text";
import { IconButton } from "@astryxdesign/core/IconButton";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { BackgroundTasksSection, type BackgroundTask } from "./BackgroundTasksSection";
import { isViewableFile, type OpenFile } from "./fileViewer";
import {
  FileIcon,
  FolderIcon,
  HtmlFileIcon,
  MarkdownFileIcon,
  PdfFileIcon,
  RefreshIcon,
} from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface TreeNode {
  name: string;
  path: string;
  is_dir: boolean;
  children?: TreeNode[];
}

interface ProjectFilePanelProps {
  projectId: string;
  projectName: string;
  folderPath: string;
  /** Change ce numero pour forcer un rechargement de l'arbre (ex. apres un
   * appel d'outil qui a pu creer/supprimer un fichier). */
  refreshSignal: number;
  tasks: BackgroundTask[];
  onOpenTask: (id: string) => void;
  onStopTask: (id: string) => void;
  onDeleteTask: (id: string) => void;
  onOpenFile: (file: OpenFile) => void;
}

/** Icone "type de fichier" style IDE pour les extensions qu'on sait
 * ouvrir dans l'app elle-meme (voir isViewableFile) - une icone generique
 * pour tout le reste, a etendre au fur et a mesure. */
function fileTypeIcon(name: string): React.ReactNode {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return <PdfFileIcon className="h-4 w-4" />;
  if (lower.endsWith(".html") || lower.endsWith(".htm")) {
    return <HtmlFileIcon className="h-4 w-4" />;
  }
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) {
    return <MarkdownFileIcon className="h-4 w-4" />;
  }
  return <FileIcon className="h-4 w-4 text-secondary" />;
}

function toTreeItems(
  nodes: TreeNode[],
  projectId: string,
  onOpenFile: (file: OpenFile) => void,
): TreeListItemData[] {
  return nodes.map((node) => ({
    id: node.path,
    label: node.name,
    startContent: node.is_dir ? (
      <FolderIcon className="h-4 w-4 text-secondary" />
    ) : (
      fileTypeIcon(node.name)
    ),
    children: node.children ? toTreeItems(node.children, projectId, onOpenFile) : undefined,
    onClick: node.is_dir
      ? undefined
      : () => {
          if (isViewableFile(node.name)) {
            onOpenFile({ projectId, path: node.path, name: node.name });
            return;
          }
          // pas de visualiseur pour ce type : ouvre avec l'application par
          // defaut du systeme (IDE, visionneuse...) comme avant
          void openPath(node.path);
        },
  }));
}

export function ProjectFilePanel({
  projectId,
  projectName,
  folderPath,
  refreshSignal,
  tasks,
  onOpenTask,
  onStopTask,
  onDeleteTask,
  onOpenFile,
}: ProjectFilePanelProps) {
  const [tree, setTree] = useState<TreeNode[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // n'appelle jamais setLoading()/setError() de facon synchrone (seulement
  // dans les callbacks .then()/.catch()/.finally()), pour pouvoir etre
  // utilisee telle quelle dans l'effet ci-dessous (voir LogsPage.tsx).
  function loadTree() {
    fetch(`${API_BASE}/projects/${projectId}/tree`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: { tree: TreeNode[]; truncated: boolean }) => {
        setError(null);
        setTree(data.tree);
        setTruncated(data.truncated);
      })
      .catch(() => {
        setError("dossier introuvable ou inaccessible.");
      })
      .finally(() => {
        setLoading(false);
      });
  }

  useEffect(loadTree, [projectId, refreshSignal]);

  return (
    <div className="flex h-full w-72 shrink-0 flex-col border-l border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <Text weight="semibold" className="block truncate">
            {projectName}
          </Text>
          <Text size="2xs" color="secondary" className="block truncate">
            {folderPath}
          </Text>
        </div>
        <IconButton
          label="Rafraîchir"
          icon={<RefreshIcon />}
          variant="ghost"
          size="sm"
          onClick={() => {
            setLoading(true);
            loadTree();
          }}
        />
      </div>

      <BackgroundTasksSection
        tasks={tasks}
        onOpen={onOpenTask}
        onStop={onStopTask}
        onDelete={onDeleteTask}
      />

      <div className="flex-1 overflow-y-auto px-2 py-2">
        {error && (
          <Text size="sm" className="block px-2 py-2 text-error">
            {error}
          </Text>
        )}
        {!error && !loading && tree.length === 0 && (
          <EmptyState title="Dossier vide" description="Ce projet ne contient aucun fichier." />
        )}
        {!error && tree.length > 0 && (
          <TreeList items={toTreeItems(tree, projectId, onOpenFile)} density="compact" />
        )}
        {truncated && (
          <Text size="2xs" color="secondary" className="block px-2 py-2">
            Certains fichiers ne sont pas affichés (dossier trop volumineux).
          </Text>
        )}
      </div>
    </div>
  );
}
