import { useState } from "react";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Text } from "@astryxdesign/core/Text";
import { DownloadIcon } from "./icons";

import { API_BASE } from "./api";

/** Sauvegarde/export complet de tout ce que le harness gere sous
 * ROOT_DIR (voir PLAN.md) : conversations, projets, memoire, snapshots,
 * config des serveurs MCP, reglages - en un seul zip, pour migrer de
 * machine ou se premunir avant une manip risquee. Le filet de securite
 * habituel (tools/snapshot.py) ne couvre que les dossiers de projet, pas
 * les donnees propres du harness. */
export function BackupSettings() {
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // fetch() + blob local plutot qu'un <a href="http://127.0.0.1:8000/...">
  // + click() direct (l'approche utilisee ailleurs, ex. App.tsx's
  // exportSession) : cette derniere navigue vers une origine differente
  // de celle de la webview Tauri, que Tauri peut bloquer silencieusement
  // sans le moindre message d'erreur - fetch() n'a pas ce probleme (deja
  // utilise partout ailleurs dans l'app sans souci), et le blob:// obtenu
  // est lui bien de la meme origine que la page, donc le download qui
  // suit est fiable.
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
        title="Contient tes clés API en clair"
        description="Le zip inclut les réglages et les configurations MCP, mais pas les clés API ni les variables secrètes MCP : elles restent dans le trousseau système. Le fichier .env, s'il existe, reste inclus et doit être conservé en lieu sûr."
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
