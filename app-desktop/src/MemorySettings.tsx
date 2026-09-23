import { useEffect, useState, type ReactNode } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { BrainIcon, ClockIcon, FolderIcon } from "./icons";

import { API_BASE } from "./api";

interface ProjectSummary {
  id: string;
  name: string;
}

interface SessionSummary {
  id: string;
  title: string | null;
  project_id: string | null;
}

/** session id in the 2026-08-28_101500 format -> "28/08/2026 10:15" - same
 * convention as App.tsx's formatSessionLabel, duplicated here rather than
 * shared (App.tsx doesn't export it for one more caller). */
function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y = "", mo = "", d = "", h = "", mi = ""] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

/** A "load/edit/save" section for a memory file's raw content (see
 * triton/storage/memory.py|projects.py|sessions.py) - the three tiers
 * (global, project, session) share this exact same GET/PUT contract
 * (content: string), only the URL changes. */
function MemoryEditor({ url, emptyHint }: { url: string | null; emptyHint: string }) {
  const [content, setContent] = useState("");
  // starts at true (no synchronous setLoading(true) in the effect - same
  // guard as McpSettings.tsx): the parent remounts this component on every
  // url change (key={url}, see MemorySettings), so this initial state
  // already covers the first load of each url.
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

/** Memory browser (see PLAN.md): the three tiers written by the remember
 * tool (tools/memory.py) - global, shared by every project, and private to
 * a project-less conversation - were until now write-only (a line appended
 * on each call, never re-read or edited other than opening the .md by
 * hand). Same three-section structure as McpSettings.tsx: one raw text
 * editor per tier, project/session memory requiring picking one first. */
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
        // only a project-less conversation has its own memory - a project
        // conversation shares the project's (see tools/memory.py's
        // remember), listing it here would just be an always-empty page.
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
