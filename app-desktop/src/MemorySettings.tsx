import { useEffect, useState } from "react";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";

const API_BASE = "http://127.0.0.1:8000";

interface ProjectSummary {
  id: string;
  name: string;
}

interface SessionSummary {
  id: string;
  title: string | null;
  project_id: string | null;
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" - meme
 * convention que App.tsx's formatSessionLabel, dupliquee ici plutot que
 * partagee (App.tsx ne l'exporte pas pour un seul appelant de plus). */
function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y = "", mo = "", d = "", h = "", mi = ""] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

/** Une section "charger/editer/sauvegarder" du contenu brut d'un fichier
 * memoire (voir triton/storage/memory.py|projects.py|sessions.py) - les
 * trois tiers (globale, projet, session) partagent exactement ce meme
 * contrat GET/PUT (content: string), seule l'URL change. */
function MemoryEditor({ url, emptyHint }: { url: string | null; emptyHint: string }) {
  const [content, setContent] = useState("");
  // demarre a true (pas de setLoading(true) synchrone dans l'effet - voir
  // McpSettings.tsx pour le meme garde-fou) : le parent remonte ce
  // composant a chaque changement d'url (key={url}, voir MemorySettings),
  // donc cet etat initial couvre deja le premier chargement de chaque url.
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!url) return;
    void fetch(url)
      .then((r) => (r.ok ? r.json() : { content: "" }))
      .then((data: { content: string }) => {
        setContent(data.content);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [url]);

  function save() {
    if (!url) return;
    setSaving(true);
    void fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    }).finally(() => {
      setSaving(false);
    });
  }

  if (!url) {
    return (
      <Text size="sm" color="secondary">
        {emptyHint}
      </Text>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <TextArea
        label="Contenu"
        isLabelHidden
        rows={8}
        value={content}
        onChange={setContent}
        isDisabled={loading}
        placeholder="(rien de mémorisé ici)"
        className="font-mono text-xs"
      />
      <div>
        <Button
          label="Sauvegarder"
          variant="secondary"
          size="sm"
          isLoading={saving}
          onClick={save}
        >
          Sauvegarder
        </Button>
      </div>
    </div>
  );
}

/** Navigateur de memoire (voir PLAN.md) : les trois tiers ecrits par le
 * tool remember (tools/memory.py) - globale, partagee par tout projet, et
 * privee a une conversation sans projet - n'etaient jusqu'ici que
 * write-only (une ligne ajoutee a chaque appel, jamais relue ni editee
 * autrement qu'en ouvrant le .md a la main). Meme structure a trois
 * sections que McpSettings.tsx : un editeur texte brut par tier, la
 * memoire de projet/session necessitant d'abord de choisir laquelle. */
export function MemorySettings() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);

  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API_BASE}/projects`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: ProjectSummary[]) => {
        setProjects(data);
      })
      .catch(() => {
        setProjects([]);
      });
    fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SessionSummary[]) => {
        // seule une conversation sans projet a sa propre memoire - une
        // conversation de projet partage celle du projet (voir
        // tools/memory.py's remember), la lister ici serait juste une
        // page toujours vide.
        setSessions(data.filter((s) => s.project_id === null));
      })
      .catch(() => {
        setSessions([]);
      });
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Text size="lg" weight="semibold" className="mb-1 block">
          Mémoire
        </Text>
        <Text size="sm" color="secondary" className="block">
          Ce que le modèle a retenu via l'outil <code>remember</code>/la commande{" "}
          <code>/remember</code> - édite ou supprime une ligne directement ici plutôt que
          d'ouvrir le fichier à la main.
        </Text>
      </div>

      <div>
        <Text weight="semibold" className="mb-2 block">
          Globale
        </Text>
        <Text size="2xs" color="secondary" className="mb-2 block">
          Partagée par toutes les conversations, tous projets confondus.
        </Text>
        <MemoryEditor url={`${API_BASE}/memory/global`} emptyHint="" />
      </div>

      <div>
        <Text weight="semibold" className="mb-2 block">
          Projet
        </Text>
        <Selector
          label="Projet"
          isLabelHidden
          options={projects.map((p) => ({ value: p.id, label: p.name }))}
          value={projectId}
          onChange={setProjectId}
          hasClear
          placeholder="Choisir un projet..."
          size="sm"
          className="mb-2"
        />
        <MemoryEditor
          key={projectId}
          url={projectId ? `${API_BASE}/projects/${projectId}/memory` : null}
          emptyHint="Choisis un projet pour voir sa mémoire."
        />
      </div>

      <div>
        <Text weight="semibold" className="mb-2 block">
          Conversation (sans projet)
        </Text>
        <Selector
          label="Conversation"
          isLabelHidden
          options={sessions.map((s) => ({
            value: s.id,
            label: s.title ?? formatSessionLabel(s.id),
          }))}
          value={sessionId}
          onChange={setSessionId}
          hasClear
          placeholder="Choisir une conversation..."
          size="sm"
          className="mb-2"
        />
        <MemoryEditor
          key={sessionId}
          url={sessionId ? `${API_BASE}/sessions/${sessionId}/memory` : null}
          emptyHint="Choisis une conversation sans projet pour voir sa mémoire."
        />
      </div>
    </div>
  );
}
