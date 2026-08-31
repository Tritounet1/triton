export interface OpenFile {
  projectId: string;
  path: string;
  name: string;
}

export type FileKind = "pdf" | "html" | "markdown";

export function fileKind(name: string): FileKind | null {
  const lower = name.toLowerCase();
  if (lower.endsWith(".pdf")) return "pdf";
  if (lower.endsWith(".html") || lower.endsWith(".htm")) return "html";
  if (lower.endsWith(".md") || lower.endsWith(".markdown")) return "markdown";
  return null;
}

/** Utilisee par ProjectFilePanel pour decider, au clic sur un fichier,
 * d'ouvrir le visualiseur (Markdown/HTML/PDF) plutot que l'application par
 * defaut du systeme. */
export function isViewableFile(name: string): boolean {
  return fileKind(name) !== null;
}
