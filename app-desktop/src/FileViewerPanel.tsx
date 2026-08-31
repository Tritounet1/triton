import { useEffect, useState } from "react";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Markdown } from "@astryxdesign/core/Markdown";
import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { fileKind, type OpenFile } from "./fileViewer";
import { HtmlFileIcon, MarkdownFileIcon, PdfFileIcon, XIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface FileViewerPanelProps {
  file: OpenFile;
  onClose: () => void;
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
  const [loading, setLoading] = useState(kind !== "pdf");
  const [error, setError] = useState<string | null>(null);

  const fileUrl = `${API_BASE}/projects/${file.projectId}/file?path=${encodeURIComponent(file.path)}`;

  useEffect(() => {
    if (kind === "pdf") return;

    fetch(fileUrl)
      .then((r) => (r.ok ? r.text() : Promise.reject(new Error(String(r.status)))))
      .then((text) => {
        setContent(text);
      })
      .catch(() => {
        setError("Impossible de charger ce fichier.");
      })
      .finally(() => {
        setLoading(false);
      });
    // fileUrl est entierement derivee de file.projectId/file.path : les
    // lister explicitement suffit, pas besoin de fileUrl elle-meme. Pas de
    // dependance a kind non plus : il derive de file.name, constant pour la
    // duree de vie de ce composant (remonte via key a chaque fichier).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file.projectId, file.path]);

  const icon =
    kind === "pdf" ? (
      <PdfFileIcon className="h-4 w-4 shrink-0" />
    ) : kind === "html" ? (
      <HtmlFileIcon className="h-4 w-4 shrink-0" />
    ) : (
      <MarkdownFileIcon className="h-4 w-4 shrink-0" />
    );

  return (
    <div className="flex h-full w-[28rem] shrink-0 flex-col border-l border-border">
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
          <IconButton label="Fermer" icon={<XIcon />} variant="ghost" size="sm" onClick={onClose} />
        </div>
      </div>

      <div className="min-h-0 flex-1">
        {kind === "pdf" && (
          <embed src={fileUrl} type="application/pdf" className="h-full w-full" />
        )}

        {kind !== "pdf" && loading && (
          <div className="flex h-full items-center justify-center">
            <Spinner size="md" />
          </div>
        )}

        {kind !== "pdf" && !loading && error && (
          <Text size="sm" className="block px-4 py-4 text-error">
            {error}
          </Text>
        )}

        {kind !== "pdf" &&
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
