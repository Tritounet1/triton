import { useEffect, useState, type ReactNode } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { BrainIcon, ClockIcon, FolderIcon } from "./icons";

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
      <div className="rounded-xl bg-muted px-3 py-3">
        <Text size="2xs" color="secondary">
          {emptyHint}
        </Text>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <TextArea
        label="Contenu"
        isLabelHidden
        rows={8}
        value={content}
        onChange={setContent}
        isDisabled={loading}
        placeholder="(rien de mémorisé ici)"
        className="font-mono text-xs leading-relaxed"
      />
      <div className="flex items-center justify-between gap-3">
        <Text size="2xs" color="secondary">
          Modifie directement le contenu brut de cette mémoire.
        </Text>
        <Button
          label="Sauvegarder"
          variant="secondary"
          size="sm"
          className="shrink-0"
          isLoading={saving}
          onClick={save}
        />
      </div>
    </div>
  );
}

function MemoryScopeCard({
  title,
  description,
  icon,
  badge,
  children,
}: {
  title: string;
  description: string;
  icon: ReactNode;
  badge?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="rounded-2xl border border-border bg-surface px-4 py-4 transition-colors hover:border-accent">
      <div className="mb-4 flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent-muted text-accent">
          {icon}
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <div className="flex flex-wrap items-center gap-2">
            <Text weight="semibold">{title}</Text>
            {badge}
          </div>
          <Text size="2xs" color="secondary" className="mt-1 block">
            {description}
          </Text>
        </div>
      </div>
      {children}
    </section>
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
    <div>
      <div className="mb-4 pr-8">
        <Text size="lg" weight="semibold" className="mb-1 block">
          Mémoire
        </Text>
        <Text size="sm" color="secondary" className="block max-w-xl">
          Consulte et corrige ce que le modèle a retenu dans chaque contexte, sans ouvrir les
          fichiers de mémoire à la main.
        </Text>
      </div>

      <div className="mb-4 flex items-start gap-3 rounded-xl bg-accent-muted px-4 py-3">
        <div className="mt-0.5 shrink-0 text-accent">
          <BrainIcon className="h-4 w-4" />
        </div>
        <Text size="2xs" color="secondary">
          Les souvenirs sont créés via <code>remember</code> ou <code>/remember</code>. Les
          modifications enregistrées ici seront utilisées au prochain échange concerné.
        </Text>
      </div>

      <div className="flex flex-col gap-3">
        <MemoryScopeCard
          title="Mémoire globale"
          description="Partagée par toutes les conversations et tous les projets."
          icon={<BrainIcon className="h-5 w-5" />}
          badge={<Badge variant="blue" label="tous les contextes" />}
        >
          <MemoryEditor url={`${API_BASE}/memory/global`} emptyHint="" />
        </MemoryScopeCard>

        <MemoryScopeCard
          title="Mémoire de projet"
          description="Partagée par les conversations rattachées au même projet."
          icon={<FolderIcon className="h-5 w-5" />}
          badge={<Badge variant="neutral" label={`${projects.length} projet${projects.length > 1 ? "s" : ""}`} />}
        >
          <Selector
            label="Projet"
            isLabelHidden
            options={projects.map((p) => ({ value: p.id, label: p.name }))}
            value={projectId}
            onChange={setProjectId}
            hasClear
            placeholder="Choisir un projet..."
            size="sm"
            className="mb-3"
          />
          <MemoryEditor
            key={projectId}
            url={projectId ? `${API_BASE}/projects/${projectId}/memory` : null}
            emptyHint="Choisis un projet pour consulter ou modifier sa mémoire."
          />
        </MemoryScopeCard>

        <MemoryScopeCard
          title="Mémoire de conversation"
          description="Disponible uniquement pour une conversation qui n'appartient pas à un projet."
          icon={<ClockIcon className="h-5 w-5" />}
          badge={<Badge variant="neutral" label={`${sessions.length} conversation${sessions.length > 1 ? "s" : ""}`} />}
        >
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
            className="mb-3"
          />
          <MemoryEditor
            key={sessionId}
            url={sessionId ? `${API_BASE}/sessions/${sessionId}/memory` : null}
            emptyHint="Choisis une conversation sans projet pour consulter sa mémoire."
          />
        </MemoryScopeCard>
      </div>
    </div>
  );
}
