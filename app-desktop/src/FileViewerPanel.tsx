import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import {
  SegmentedControl,
  SegmentedControlItem,
} from "@astryxdesign/core/SegmentedControl";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { useEffect, useState } from "react";
import { fileKind, type OpenFile } from "./fileViewer";
import { HtmlFileIcon, ImageIcon, MarkdownFileIcon, PdfFileIcon, XIcon } from "./icons";

import { API_BASE } from "./api";

interface FileViewerPanelProps {
  file: OpenFile;
  onClose: () => void;
}

function parseCsv(content: string): string[][] {
  return content
    .trim()
    .split(/\r?\n/)
    .slice(0, 200)
    .map((line) => line.split(",").map((cell) => cell.trim()));
}

/** Panneau de lecture Markdown/HTML/PDF pour un fichier d'un projet, meme
 * emplacement que ProjectFilePanel (le remplace tant qu'un fichier est
 * ouvert) - style Claude Desktop : en-tete avec le nom du fichier, un
 * bouton fermer, et pour HTML/Markdown un bascule Apercu/Code. Le PDF est
 * affiche via <embed>, le navigateur systeme (WKWebView) le rend nativement
 * sans bibliotheque JS supplementaire.
 *
 * App.tsx monte ce composant avec `key={file.path}` : un nouveau fichier
 * remonte le composant plutot que de reutiliser l'instance, donc l'etat
 * (mode/content/error/loading) repart de zero via les valeurs initiales de
 * useState au lieu d'etre reinitialise a la main dans l'effet (ce qui
 * demanderait un setState synchrone au corps de l'effet, interdit par
 * react-hooks/set-state-in-effect - voir McpSettings.tsx pour le meme
 * garde-fou). */
export function FileViewerPanel({ file, onClose }: FileViewerPanelProps) {
  const kind = fileKind(file.name);
  const [mode, setMode] = useState<"code" | "render">("render");
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(kind !== "pdf" && kind !== "image");
  const [error, setError] = useState<string | null>(null);

  const fileUrl = `${API_BASE}/projects/${file.projectId}/file?path=${encodeURIComponent(file.path)}`;

  useEffect(() => {
    if (kind === "pdf" || kind === "image") return;

    void (async () => {
      try {
        const response = await fetch(fileUrl);
        if (!response.ok) throw new Error(String(response.status));
        setContent(await response.text());
      } catch {
        setError("Impossible de charger ce fichier.");
      } finally {
        setLoading(false);
      }
    })();
    // fileUrl is entirely derived from file.projectId/file.path: listing
    // those explicitly is enough, no need for fileUrl itself. No dependency
    // on kind either: it derives from file.name, constant for this
    // component's lifetime (remounted via key on each file).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file.projectId, file.path]);

  const icon =
    kind === "pdf" ? (
      <PdfFileIcon className="h-4 w-4 shrink-0" />
    ) : kind === "html" ? (
      <HtmlFileIcon className="h-4 w-4 shrink-0" />
    ) : kind === "image" ? (
      <ImageIcon className="h-4 w-4 shrink-0" />
    ) : (
      <MarkdownFileIcon className="h-4 w-4 shrink-0" />
    );

  return (
    <div className="flex h-full w-[46rem] shrink-0 flex-col border-l border-border">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <Text weight="semibold" className="block truncate">
            {file.name}
          </Text>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {kind !== "pdf" && (
            <SegmentedControl
              value={mode}
              onChange={(v) => {
                setMode(v as "code" | "render");
              }}
              label="Affichage"
              size="sm"
            >
              <SegmentedControlItem label="Aperçu" value="render" />
              <SegmentedControlItem label="Code" value="code" />
            </SegmentedControl>
          )}
          <a
            href={fileUrl}
            download={file.name}
            className="rounded-md px-2 py-1 text-xs text-secondary hover:bg-surface-hover hover:text-primary"
          >
            Télécharger
          </a>
          <IconButton
            label="Fermer"
            icon={<XIcon />}
            variant="ghost"
            size="sm"
            onClick={onClose}
          />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {kind === "pdf" && (
          <embed
            src={fileUrl}
            type="application/pdf"
            className="h-full w-full"
          />
        )}

        {kind === "image" && (
          <div className="flex h-full items-center justify-center overflow-auto bg-surface-subtle p-4">
            <img src={fileUrl} alt={file.name} className="max-h-full max-w-full rounded-md shadow-sm" />
          </div>
        )}

        {kind !== "pdf" && kind !== "image" && loading && (
          <div className="flex h-full items-center justify-center">
            <Spinner size="md" />
          </div>
        )}

        {kind !== "pdf" && kind !== "image" && !loading && error && (
          <Text size="sm" className="block px-4 py-4 text-error">
            {error}
          </Text>
        )}

        {kind !== "pdf" &&
          kind !== "image" &&
          !loading &&
          !error &&
          content !== null &&
          (mode === "code" ? (
            <pre className="h-full overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs">
              {content}
            </pre>
          ) : kind === "markdown" ? (
            <div className="h-full overflow-auto px-4 py-3">
              <Markdown>{content}</Markdown>
            </div>
          ) : kind === "csv" ? (
            <div className="h-full overflow-auto p-3">
              <table className="w-full border-collapse text-left text-xs">
                <tbody>
                  {parseCsv(content).map((row, rowIndex) => (
                    <tr key={rowIndex} className={rowIndex === 0 ? "bg-surface-subtle font-semibold" : "border-t border-border"}>
                      {row.map((cell, cellIndex) => (
                        <td key={cellIndex} className="max-w-72 truncate px-2 py-1.5">{cell}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <iframe
              srcDoc={content}
              sandbox="allow-scripts"
              className="h-full w-full border-0 bg-white"
              title={file.name}
            />
          ))}
      </div>
    </div>
  );
}
