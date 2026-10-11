import { useEffect, useState } from "react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ArrowLeftIcon, BrainIcon, FileIcon, FolderIcon, SearchIcon, TerminalIcon } from "./icons";
import { API_BASE } from "./api";

type SearchKind = "conversation" | "file" | "task" | "memory";

interface SearchResult {
  id: string;
  kind: SearchKind;
  title: string;
  excerpt: string;
  project_id: string | null;
  project_name: string | null;
  session_id: string | null;
  task_id: string | null;
  path: string | null;
  modified_at: string;
}

interface Project { id: string; name: string }

interface SearchPageProps {
  onBack: () => void;
  onSelectSession: (id: string) => void;
  onSelectTask: (id: string) => void;
  onSelectProject: (id: string) => void;
}

const FILTERS: { value: SearchKind | ""; label: string }[] = [
  { value: "", label: "Tout" }, { value: "conversation", label: "Conversations" },
  { value: "file", label: "Fichiers" }, { value: "task", label: "Tâches" },
  { value: "memory", label: "Notes" },
];

function kindLabel(kind: SearchKind): string {
  return { conversation: "Conversation", file: "Fichier", task: "Tâche", memory: "Note" }[kind];
}

function kindIcon(kind: SearchKind) {
  const className = "h-4 w-4 text-secondary";
  if (kind === "file") return <FileIcon className={className} />;
  if (kind === "task") return <TerminalIcon className={className} />;
  if (kind === "memory") return <BrainIcon className={className} />;
  return <SearchIcon className={className} />;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "" : new Intl.DateTimeFormat("fr-FR", { dateStyle: "short", timeStyle: "short" }).format(date);
}

export function SearchPage({ onBack, onSelectSession, onSelectTask, onSelectProject }: SearchPageProps) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<SearchKind | "">("");
  const [projectId, setProjectId] = useState("");
  const [period, setPeriod] = useState("all");
  const [projects, setProjects] = useState<Project[]>([]);
  const [results, setResults] = useState<SearchResult[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/projects`).then((response) => response.ok ? response.json() : [])
      .then((data: Project[]) => { setProjects(data); }).catch(() => { setProjects([]); });
  }, []);

  useEffect(() => {
    const timeout = setTimeout(() => {
      const params = new URLSearchParams({ period });
      if (query.trim()) params.set("q", query.trim());
      if (kind) params.set("types", kind);
      if (projectId) params.set("project_id", projectId);
      setLoading(true);
      fetch(`${API_BASE}/search?${params.toString()}`).then((response) => response.ok ? response.json() : [])
        .then((data: SearchResult[]) => { setResults(data); }).catch(() => { setResults([]); }).finally(() => { setLoading(false); });
    }, query ? 250 : 0);
    return () => { clearTimeout(timeout); };
  }, [kind, period, projectId, query]);

  function selectResult(result: SearchResult) {
    if (result.kind === "conversation" && result.session_id) onSelectSession(result.session_id);
    else if (result.kind === "task" && result.task_id) onSelectTask(result.task_id);
    else if (result.project_id) onSelectProject(result.project_id);
    else if (result.session_id) onSelectSession(result.session_id);
  }

  const hasQuery = query.trim().length > 0;
  return (
    <div className="mx-auto flex h-full w-full max-w-4xl flex-col px-6 py-10">
      <div className="mb-8 flex items-center gap-3"><IconButton label="Retour" icon={<ArrowLeftIcon />} variant="ghost" size="sm" onClick={onBack} /></div>
      <TextInput value={query} onChange={setQuery} placeholder="Rechercher une conversation, un fichier, une tâche ou une note..." isLabelHidden label="Recherche globale" size="lg" hasAutoFocus startIcon={<SearchIcon className="h-4 w-4 text-secondary" />} />
      <div className="mt-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((filter) => <button key={filter.value || "all"} type="button" onClick={() => { setKind(filter.value); }} className={`rounded-full px-3 py-1.5 text-sm ${kind === filter.value ? "bg-foreground text-background" : "bg-muted hover:bg-muted/70"}`}>{filter.label}</button>)}
        <label className="sr-only" htmlFor="search-project">Projet</label>
        <select id="search-project" value={projectId} onChange={(event) => { setProjectId(event.target.value); }} className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"><option value="">Tous les projets</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
        <label className="sr-only" htmlFor="search-period">Période</label>
        <select id="search-period" value={period} onChange={(event) => { setPeriod(event.target.value); }} className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"><option value="all">Toutes les dates</option><option value="day">24 dernières heures</option><option value="week">7 derniers jours</option><option value="month">30 derniers jours</option><option value="year">Cette année</option></select>
      </div>
      <div className="mt-7 flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pb-8">
        <Text size="sm" color="secondary">{hasQuery ? "Résultats" : "Notes récentes"}{!loading && ` · ${results.length}`}</Text>
        {!loading && results.length === 0 && <EmptyState title="Aucun résultat" description={hasQuery ? "Aucun élément ne correspond à cette recherche." : "Aucun élément récent à afficher."} />}
        {results.map((result) => {
          const interactive = Boolean(result.session_id ?? result.task_id ?? result.project_id);
          const content = <><span className="flex shrink-0 rounded-md bg-muted p-2">{kindIcon(result.kind)}</span><span className="min-w-0 flex-1"><span className="flex items-center gap-2"><Text weight="medium" className="truncate">{result.title}</Text><span className="rounded bg-muted px-1.5 py-0.5 text-2xs text-secondary">{kindLabel(result.kind)}</span></span>{result.excerpt && <Text size="sm" color="secondary" className="mt-0.5 block line-clamp-2">{result.excerpt}</Text>}<span className="mt-1 flex items-center gap-2 text-2xs text-secondary">{result.project_name && <span className="flex items-center gap-1"><FolderIcon className="h-3 w-3" />{result.project_name}</span>}<span>{formatDate(result.modified_at)}</span></span></span></>;
          return interactive ? <button key={result.id} type="button" onClick={() => { selectResult(result); }} className="flex w-full items-start gap-3 rounded-lg border border-border px-3 py-3 text-left hover:bg-muted">{content}</button> : <div key={result.id} className="flex items-start gap-3 rounded-lg border border-border px-3 py-3">{content}</div>;
        })}
      </div>
    </div>
  );
}
