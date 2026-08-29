import { useEffect, useState } from "react";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Text } from "@astryxdesign/core/Text";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ArrowLeftIcon, SearchIcon } from "./icons";

const API_BASE = "http://127.0.0.1:8000";

interface Session {
  id: string;
  title: string | null;
  project_id: string | null;
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" */
function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y = "", mo = "", d = "", h = "", mi = ""] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

interface SearchPageProps {
  onBack: () => void;
  onSelectSession: (id: string) => void;
}

/** Page de recherche a part entiere (au lieu d'un champ deroulant dans la
 * sidebar) : un champ centre, les resultats apparaissent en dessous au fil
 * de la frappe - titre (instantane) et contenu des messages (debounce,
 * /sessions/search cote serveur). */
export function SearchPage({ onBack, onSelectSession }: SearchPageProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [query, setQuery] = useState("");
  const [contentMatchIds, setContentMatchIds] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    fetch(`${API_BASE}/sessions`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: Session[]) => {
        setSessions(data);
      })
      .catch(() => {
        // API hors ligne : la recherche reste vide
      });
  }, []);

  useEffect(() => {
    const trimmed = query.trim();
    const timeout = setTimeout(() => {
      if (!trimmed) {
        setContentMatchIds(new Set());
        return;
      }
      fetch(`${API_BASE}/sessions/search?q=${encodeURIComponent(trimmed)}`)
        .then((r) => (r.ok ? r.json() : []))
        .then((ids: string[]) => {
          setContentMatchIds(new Set(ids));
        })
        .catch(() => {
          // API hors ligne : la recherche par titre (instantanee) continue de fonctionner
        });
    }, 300);
    return () => {
      clearTimeout(timeout);
    };
  }, [query]);

  const trimmed = query.trim();
  const results = trimmed
    ? sessions.filter((s) => {
        if (s.project_id !== null) return false;
        const titleMatches = (s.title ?? formatSessionLabel(s.id))
          .toLowerCase()
          .includes(trimmed.toLowerCase());
        return titleMatches || contentMatchIds.has(s.id);
      })
    : [];

  return (
    <div className="mx-auto flex h-full max-w-2xl flex-col px-6 py-10">
      <div className="mb-8 flex items-center gap-3">
        <IconButton label="Retour" icon={<ArrowLeftIcon />} variant="ghost" size="sm" onClick={onBack} />
      </div>

      <TextInput
        value={query}
        onChange={setQuery}
        placeholder="Rechercher une conversation, par titre ou par contenu..."
        isLabelHidden
        label="Rechercher une conversation"
        size="lg"
        hasAutoFocus
        startIcon={<SearchIcon className="h-4 w-4 text-secondary" />}
      />

      <div className="mt-6 flex flex-col gap-1">
        {trimmed && results.length === 0 && (
          <EmptyState
            title="Aucun résultat"
            description="Aucune conversation ne correspond à cette recherche."
          />
        )}
        {results.map((s) => (
          <button
            key={s.id}
            onClick={() => {
              onSelectSession(s.id);
            }}
            className="rounded-lg px-3 py-2 text-left hover:bg-muted"
          >
            <Text weight="medium" className="block truncate">
              {s.title ?? formatSessionLabel(s.id)}
            </Text>
          </button>
        ))}
      </div>
    </div>
  );
}
