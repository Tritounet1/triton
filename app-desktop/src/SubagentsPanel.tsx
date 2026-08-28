import { useEffect, useState } from "react";
import { Badge } from "@astryxdesign/core/Badge";
import { SideNavSection, SideNavItem } from "@astryxdesign/core/SideNav";
import { Text } from "@astryxdesign/core/Text";

const API_BASE = "http://127.0.0.1:8000";
const POLL_INTERVAL_MS = 3000;

interface SubagentTask {
  id: string;
  task: string;
  status: "running" | "done" | "error";
  result: string | null;
  created_at: string;
}

function statusBadgeVariant(status: SubagentTask["status"]): "success" | "error" | "neutral" {
  if (status === "done") return "success";
  if (status === "error") return "error";
  return "neutral";
}

function statusLabel(status: SubagentTask["status"]): string {
  if (status === "running") return "en cours";
  if (status === "error") return "échec";
  return "terminé";
}

/** Sous-agents lancés par le modèle (tool dispatch_subagent) : tournent en
 * fond dans le harness, ce panneau se contente d'interroger leur etat
 * periodiquement (pas de flux temps reel dedie, cf. PLAN.md). */
export function SubagentsPanel() {
  const [tasks, setTasks] = useState<SubagentTask[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  function loadTasks() {
    fetch(`${API_BASE}/subagents`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: SubagentTask[]) => { setTasks(data); })
      .catch(() => {
        // API hors ligne : la liste reste telle quelle
      });
  }

  useEffect(() => {
    loadTasks();
    const interval = setInterval(loadTasks, POLL_INTERVAL_MS);
    return () => { clearInterval(interval); };
  }, []);

  if (tasks.length === 0) return null;

  return (
    <SideNavSection title="Sous-agents">
      {tasks.map((t) => (
        <div key={t.id}>
          <SideNavItem
            label={t.task}
            endContent={<Badge variant={statusBadgeVariant(t.status)} label={statusLabel(t.status)} />}
            onClick={() => { setExpandedId((cur) => (cur === t.id ? null : t.id)); }}
          />
          {expandedId === t.id && t.result && (
            <Text size="2xs" color="secondary" className="block whitespace-pre-wrap px-3 py-1">
              {t.result}
            </Text>
          )}
        </div>
      ))}
    </SideNavSection>
  );
}
