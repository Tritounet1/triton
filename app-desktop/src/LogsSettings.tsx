import { useEffect, useMemo, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Table, proportional, pixel, type TableColumn } from "@astryxdesign/core/Table";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { RefreshIcon } from "./icons";
import { formatArgs, formatDuration } from "./format";

const API_BASE = "http://127.0.0.1:8000";

interface ModelCallEvent {
  [key: string]: unknown;
  type: "model_call";
  timestamp: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  tool_calls: number;
  duration_seconds: number;
  cost_usd?: number;
}

interface SubagentModelCallEvent {
  [key: string]: unknown;
  type: "subagent_model_call";
  timestamp: string;
  subagent_id: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  tool_calls: number;
  cost_usd?: number;
}

interface ToolCallEvent {
  [key: string]: unknown;
  type: "tool_call";
  timestamp: string;
  tool: string;
  args: Record<string, unknown>;
  result_preview: string;
  result_chars: number;
  duration_seconds: number;
}

type LogEvent = ModelCallEvent | SubagentModelCallEvent | ToolCallEvent;
type CostEvent = ModelCallEvent | SubagentModelCallEvent;

function isModelCall(e: LogEvent): e is ModelCallEvent {
  return e.type === "model_call";
}

function isSubagentModelCall(e: LogEvent): e is SubagentModelCallEvent {
  return e.type === "subagent_model_call";
}

function isToolCall(e: LogEvent): e is ToolCallEvent {
  return e.type === "tool_call";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR");
}

function toolFailed(result: string): boolean {
  return result.startsWith("error") || result.startsWith("action denied");
}

function formatCost(v: number): string {
  if (v <= 0) return "$0.00";
  if (v < 0.01) return "<$0.01";
  return `$${v.toFixed(2)}`;
}

interface StatTileProps {
  label: string;
  value: string;
}

function StatTile({ label, value }: StatTileProps) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <Text size="2xs" color="secondary" className="block uppercase tracking-wide">
        {label}
      </Text>
      <Text size="xl" weight="semibold" className="block">
        {value}
      </Text>
    </div>
  );
}

const CHART_DAYS = 14;
const CHART_HEIGHT_PX = 140;

interface DayStats {
  date: string;
  tokens: number;
  cost: number;
}

function toDayKey(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso.slice(0, 10) : d.toISOString().slice(0, 10);
}

function formatDayLabel(dayKey: string): string {
  const d = new Date(dayKey);
  return Number.isNaN(d.getTime())
    ? dayKey
    : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
}

/** Agrège tokens + coût par jour en un seul passage (appels principaux et
 * sous-agents confondus, cf. costEvents plus bas) : "un suivi des coûts
 * réels" doit compter tout ce qui coûte vraiment de l'argent, pas juste la
 * boucle principale. */
function useDailyStats(events: CostEvent[]): DayStats[] {
  return useMemo(() => {
    if (events.length === 0) return [];

    const byDay = new Map<string, { tokens: number; cost: number }>();
    for (const e of events) {
      const key = toDayKey(e.timestamp);
      const entry = byDay.get(key) ?? { tokens: 0, cost: 0 };
      entry.tokens += e.total_tokens;
      entry.cost += e.cost_usd ?? 0;
      byDay.set(key, entry);
    }

    // comble les jours sans appel (barre a 0) pour un axe continu, du plus
    // ancien jour observe jusqu'a aujourd'hui, puis ne garde que les
    // CHART_DAYS derniers jours
    const earliest = [...byDay.keys()].sort()[0];
    if (!earliest) return [];
    const days: DayStats[] = [];
    for (let d = new Date(earliest); d <= new Date(); d.setDate(d.getDate() + 1)) {
      const key = d.toISOString().slice(0, 10);
      const entry = byDay.get(key) ?? { tokens: 0, cost: 0 };
      days.push({ date: key, tokens: entry.tokens, cost: entry.cost });
    }
    return days.slice(-CHART_DAYS);
  }, [events]);
}

interface DailyBarChartProps {
  days: DayStats[];
  title: string;
  getValue: (d: DayStats) => number;
  formatValue: (v: number) => string;
}

function DailyBarChart({ days, title, getValue, formatValue }: DailyBarChartProps) {
  if (days.length === 0) return null;
  const max = Math.max(1, ...days.map(getValue));

  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-4">
      <Text size="2xs" color="secondary" className="mb-3 block uppercase tracking-wide">
        {title}
      </Text>
      <div className="flex items-end gap-1.5" style={{ height: CHART_HEIGHT_PX }}>
        {days.map((d) => {
          const value = getValue(d);
          return (
            <div
              key={d.date}
              title={`${formatDayLabel(d.date)} : ${formatValue(value)}`}
              className="flex-1 rounded-t bg-accent transition-[height] hover:opacity-80"
              style={{ height: `${Math.max(value > 0 ? 3 : 0, (value / max) * 100)}%` }}
            />
          );
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {days.map((d) => (
          <Text key={d.date} size="2xs" color="secondary" className="flex-1 text-center">
            {formatDayLabel(d.date)}
          </Text>
        ))}
      </div>
    </div>
  );
}

export function LogsSettings() {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [budget, setBudget] = useState<number | null>(null);
  const [budgetInput, setBudgetInput] = useState<number | null>(null);
  const [savingBudget, setSavingBudget] = useState(false);

  // n'appelle jamais setLoading() de facon synchrone (seulement dans les
  // callbacks .then()/.catch()/.finally()), pour pouvoir etre utilisee
  // telle quelle dans l'effet de montage ci-dessous : react-hooks
  // (set-state-in-effect) interdit d'appeler setState de facon synchrone
  // dans le corps d'un effet.
  function fetchLogs() {
    fetch(`${API_BASE}/logs`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: LogEvent[]) => { setEvents(data); })
      .catch(() => { setEvents([]); })
      .finally(() => { setLoading(false); });
  }

  function fetchBudget() {
    fetch(`${API_BASE}/settings/budget`)
      .then((r) => (r.ok ? r.json() : { monthly_budget_usd: null }))
      .then((data: { monthly_budget_usd: number | null }) => {
        setBudget(data.monthly_budget_usd);
        setBudgetInput(data.monthly_budget_usd);
      })
      .catch(() => {
        // API hors ligne : le budget reste tel quel
      });
  }

  // pour le bouton "rafraichir" : la remise a `true` de loading doit rester
  // synchrone (affichage immediat du spinner), ce qui est permis dans un
  // gestionnaire d'evenement (juste pas dans un effet).
  function refresh() {
    setLoading(true);
    fetchLogs();
  }

  function loadAll() {
    fetchLogs();
    fetchBudget();
  }

  useEffect(loadAll, []);

  async function saveBudget() {
    setSavingBudget(true);
    try {
      const res = await fetch(`${API_BASE}/settings/budget`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ monthly_budget_usd: budgetInput }),
      });
      if (res.ok) setBudget(budgetInput);
    } finally {
      setSavingBudget(false);
    }
  }

  const modelCalls = useMemo(() => events.filter(isModelCall), [events]);
  const subagentModelCalls = useMemo(() => events.filter(isSubagentModelCall), [events]);
  const toolCalls = useMemo(() => events.filter(isToolCall), [events]);
  const costEvents = useMemo(
    () => [...modelCalls, ...subagentModelCalls],
    [modelCalls, subagentModelCalls],
  );

  const totalTokens = useMemo(
    () => costEvents.reduce((sum, e) => sum + e.total_tokens, 0),
    [costEvents],
  );
  const totalCost = useMemo(
    () => costEvents.reduce((sum, e) => sum + (e.cost_usd ?? 0), 0),
    [costEvents],
  );

  const currentMonthCost = useMemo(() => {
    const monthKey = new Date().toISOString().slice(0, 7);
    return costEvents
      .filter((e) => e.timestamp.startsWith(monthKey))
      .reduce((sum, e) => sum + (e.cost_usd ?? 0), 0);
  }, [costEvents]);

  const days = useDailyStats(costEvents);

  const topTool = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of toolCalls) counts.set(t.tool, (counts.get(t.tool) ?? 0) + 1);
    const sorted = [...counts.entries()].sort((a, b) => b[1] - a[1]);
    return sorted[0];
  }, [toolCalls]);

  const modelColumns: TableColumn<ModelCallEvent>[] = [
    {
      key: "timestamp",
      header: "Heure",
      width: pixel(170),
      renderCell: (e) => <Text size="sm">{formatTime(e.timestamp)}</Text>,
    },
    {
      key: "model",
      header: "Modèle",
      width: proportional(2),
      renderCell: (e) => <Text size="sm">{e.model}</Text>,
    },
    {
      key: "tokens",
      header: "Tokens",
      width: pixel(160),
      renderCell: (e) => (
        <Text size="sm">
          {e.total_tokens} ({e.prompt_tokens}+{e.completion_tokens})
        </Text>
      ),
    },
    {
      key: "cost",
      header: "Coût",
      width: pixel(90),
      align: "end",
      renderCell: (e) => (
        <Text size="sm">{e.cost_usd !== undefined ? formatCost(e.cost_usd) : "-"}</Text>
      ),
    },
    {
      key: "tool_calls",
      header: "Outils",
      width: pixel(80),
      align: "center",
      renderCell: (e) => <Text size="sm">{e.tool_calls || "-"}</Text>,
    },
    {
      key: "duration_seconds",
      header: "Durée",
      width: pixel(90),
      align: "end",
      renderCell: (e) => <Text size="sm">{formatDuration(e.duration_seconds)}</Text>,
    },
  ];

  const toolColumns: TableColumn<ToolCallEvent>[] = [
    {
      key: "timestamp",
      header: "Heure",
      width: pixel(170),
      renderCell: (e) => <Text size="sm">{formatTime(e.timestamp)}</Text>,
    },
    {
      key: "tool",
      header: "Outil",
      width: proportional(1),
      renderCell: (e) => (
        <code className="rounded bg-muted px-1.5 py-0.5 text-xs">{e.tool}</code>
      ),
    },
    {
      key: "args",
      header: "Arguments",
      width: proportional(2),
      renderCell: (e) => (
        <Text size="sm" className="block truncate">
          {formatArgs(e.args)}
        </Text>
      ),
    },
    {
      key: "result",
      header: "Résultat",
      width: pixel(110),
      align: "center",
      renderCell: (e) => (
        <Badge
          variant={toolFailed(e.result_preview) ? "error" : "success"}
          label={toolFailed(e.result_preview) ? "échec" : "ok"}
        />
      ),
    },
    {
      key: "duration_seconds",
      header: "Durée",
      width: pixel(90),
      align: "end",
      renderCell: (e) => <Text size="sm">{formatDuration(e.duration_seconds)}</Text>,
    },
  ];

  const budgetExceeded = budget !== null && currentMonthCost > budget;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <Text size="lg" weight="semibold">
          Logs &amp; coûts
        </Text>
        <IconButton
          label="Rafraîchir"
          icon={<RefreshIcon />}
          variant="ghost"
          size="sm"
          onClick={refresh}
        />
      </div>

      {!loading && events.length === 0 ? (
        <EmptyState
          title="Aucun log pour l'instant"
          description="Les appels au modèle et aux outils apparaîtront ici au fil des conversations."
        />
      ) : (
        <>
          {budgetExceeded && (
            <Banner
              status="warning"
              title="Budget mensuel dépassé"
              description={`${formatCost(currentMonthCost)} dépensés ce mois-ci, pour un budget de ${formatCost(budget)}.`}
              className="mb-6"
            />
          )}

          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Appels modèle" value={String(costEvents.length)} />
            <StatTile label="Tokens totaux" value={totalTokens.toLocaleString("fr-FR")} />
            <StatTile label="Coût total" value={formatCost(totalCost)} />
            <StatTile label="Outil le plus utilisé" value={topTool ? topTool[0] : "-"} />
          </div>

          <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            <DailyBarChart
              days={days}
              title="Tokens consommés par jour"
              getValue={(d) => d.tokens}
              formatValue={(v) => `${v.toLocaleString("fr-FR")} tokens`}
            />
            <DailyBarChart
              days={days}
              title="Coût par jour"
              getValue={(d) => d.cost}
              formatValue={formatCost}
            />
          </div>

          <div className="mb-8 flex items-end gap-3 rounded-xl border border-border bg-surface px-4 py-3">
            <NumberInput
              label="Budget mensuel (USD)"
              value={budgetInput}
              onChange={setBudgetInput}
              min={0}
              size="sm"
              placeholder="Pas de budget défini"
              className="max-w-48"
            />
            <Button
              label="Enregistrer"
              variant="secondary"
              size="sm"
              isLoading={savingBudget}
              onClick={() => { void saveBudget(); }}
            />
            <Text size="2xs" color="secondary" className="ml-auto">
              Dépensé ce mois-ci : {formatCost(currentMonthCost)}
            </Text>
          </div>

          <Text size="sm" weight="semibold" className="mb-2 block">
            Appels au modèle
          </Text>
          <div className="mb-8 overflow-hidden rounded-xl border border-border">
            <Table data={modelCalls} columns={modelColumns} density="compact" hasHover />
          </div>

          <Text size="sm" weight="semibold" className="mb-2 block">
            Appels d'outils
          </Text>
          <div className="overflow-hidden rounded-xl border border-border">
            <Table data={toolCalls} columns={toolColumns} density="compact" hasHover />
          </div>
        </>
      )}
    </div>
  );
}
