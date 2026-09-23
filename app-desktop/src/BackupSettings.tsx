import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { DownloadIcon } from "./icons";

import { API_BASE } from "./api";

/** Full backup/export of everything the harness manages under ROOT_DIR (see
 * PLAN.md): conversations, projects, memory, snapshots, MCP server config,
 * settings - as a single zip, for migrating machines or as a precaution
 * before a risky operation. The usual safety net (tools/snapshot.py) only
 * covers project folders, not the harness's own data. */
export function BackupSettings() {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // fetch() + local blob rather than a direct <a href="http://127.0.0.1:8000/...">
  // + click() (the approach used elsewhere, e.g. App.tsx's exportSession):
  // the latter navigates to a different origin than the Tauri webview's
  // own, which Tauri can silently block with no error message at all -
  // fetch() doesn't have this problem (already used everywhere else in the
  // app without issue), and the resulting blob:// is same-origin as the
  // page, so the download that follows is reliable.
  async function downloadBackup() {
    setDownloading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/backup/export`);
      if (!res.ok) {
        setError(`échec du téléchargement (erreur ${res.status}).`);
        return;
      }
      const blob = await res.blob();
      const disposition = res.headers.get("Content-Disposition") ?? "";
      const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "triton-backup.zip";

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch {
      setError("impossible de contacter l'API Triton (127.0.0.1:8000).");
    } finally {
      setDownloading(false);
    }
  }

  return (
    <div>
      <Text size="lg" weight="semibold" className="mb-4 block">
        Sauvegarde
      </Text>

      <Text size="sm" color="secondary" className="mb-4 block">
        Télécharge un zip de tout ce que Triton gère sur cette machine :
        conversations, projets, mémoire, points de restauration, configuration
        des serveurs MCP et réglages. Utile pour migrer vers une autre machine
        ou se prémunir avant une manipulation risquée.
      </Text>

      <Banner
        status="warning"
        title="Le fichier .env reste inclus tel quel, s'il existe"
        description="Les clés API et les secrets des serveurs MCP restent dans le trousseau système (ou dans un fichier séparé hors macOS) et ne sont jamais dans ce zip. Un fichier .env local, lui, l'est encore tel quel - à garder aussi en sécurité que lui."
        className="mb-6"
      />

      <Button
        label="Télécharger la sauvegarde"
        variant="primary"
        icon={<DownloadIcon />}
        isLoading={downloading}
        onClick={() => {
          void downloadBackup();
        }}
      >
        Télécharger la sauvegarde
      </Button>

      {error && (
        <Text size="sm" className="mt-3 block text-error">
          {error}
        </Text>
      )}
    </div>
  );
}
