import { useEffect, useMemo, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { NumberInput } from "@astryxdesign/core/NumberInput";
import { Table, proportional, pixel, type TableColumn } from "@astryxdesign/core/Table";
import { Tooltip } from "@astryxdesign/core/Tooltip";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { RefreshIcon } from "./icons";
import { formatArgs, formatDuration } from "./format";

import { API_BASE } from "./api";

interface ModelCallEvent {
  [key: string]: unknown;
  type: "model_call";
  timestamp: string;
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  // absent sur certains logs anciens (le champ a ete ajoute apres coup) -
  // toujours traite comme 0 plutot que NaN dans les sommes ci-dessous.
  total_tokens?: number;
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
  total_tokens?: number;
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

interface ModelCostBreakdown {
  [key: string]: unknown;
  model: string;
  calls: number;
  total_tokens: number;
  cost_usd: number;
}

interface ProjectCostBreakdown {
  [key: string]: unknown;
  project_id: string | null;
  project_name: string;
  calls: number;
  total_tokens: number;
  cost_usd: number;
}

interface DayCostBreakdown {
  date: string;
  calls: number;
  total_tokens: number;
  cost_usd: number;
}

interface CostSummary {
  month: string;
  total_calls: number;
  total_tokens: number;
  total_cost_usd: number;
  by_model: ModelCostBreakdown[];
  by_project: ProjectCostBreakdown[];
  by_day: DayCostBreakdown[];
}

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
const VISIBLE_ROWS = 25;

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
      entry.tokens += e.total_tokens ?? 0;
      entry.cost += e.cost_usd ?? 0;
      byDay.set(key, entry);
    }

    return completeDailyStats(
      [...byDay].map(([date, values]) => ({ date, tokens: values.tokens, cost: values.cost })),
    );
  }, [events]);
}

/** Comble les jours sans appel pour conserver un axe continu. Le résumé
 * mensuel du serveur et le repli sur les logs récents passent par la même
 * normalisation, donc le graphique ne change pas de forme si l'endpoint de
 * synthèse est momentanément indisponible. */
function completeDailyStats(observed: DayStats[]): DayStats[] {
  if (observed.length === 0) return [];
  const byDay = new Map(observed.map((day) => [day.date, day]));
  const earliest = [...byDay.keys()].sort()[0];
  if (!earliest) return [];

  const days: DayStats[] = [];
  for (let d = new Date(earliest); d <= new Date(); d.setDate(d.getDate() + 1)) {
    const key = d.toISOString().slice(0, 10);
    days.push(byDay.get(key) ?? { date: key, tokens: 0, cost: 0 });
  }
  return days.slice(-CHART_DAYS);
}

interface DailyBarChartProps {
  days: DayStats[];
  title: string;
  getValue: (d: DayStats) => number;
}

/** Contenu du survol d'une barre : tokens ET coût ensemble, quel que soit
 * le graphique survolé (celui des tokens ou celui du coût) - une seule
 * des deux valeurs ne suffit pas a repondre a "qu'est-ce qui a coute cher
 * ce jour-la", il faut les deux d'un coup d'oeil.
 *
 * Du HTML brut plutot que <Text> ici : le fond du Tooltip est sombre par
 * design (couleurs inversees pour le contraste, cf. sa propre doc), mais
 * <Text color="secondary"> est calibree pour un fond clair - un gris sur
 * fond deja sombre devenait illisible. text-on-dark force un blanc fixe,
 * correct quel que soit le theme clair/sombre de l'appli elle-meme. */
function DayTooltipContent({ d }: { d: DayStats }) {
  return (
    <div className="flex flex-col gap-0.5 px-1 py-0.5 text-on-dark">
      <span className="text-xs font-semibold">{formatDayLabel(d.date)}</span>
      <span className="text-[11px] opacity-80">{d.tokens.toLocaleString("fr-FR")} tokens</span>
      <span className="text-[11px] opacity-80">{formatCost(d.cost)}</span>
    </div>
  );
}

function DailyBarChart({ days, title, getValue }: DailyBarChartProps) {
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
            <Tooltip key={d.date} content={<DayTooltipContent d={d} />}>
              <div
                // bg-accent (quasi-noir dans ce theme neutre) rendait les
                // barres et la tooltip presque indissociables, tout
                // paraissait sombre d'un bloc - bleu vif plus doux, meme
                // couleur que le badge/texte "info" utilise ailleurs.
                className="flex-1 rounded-t bg-blue-vivid transition-[height] hover:opacity-80"
                style={{ height: `${Math.max(value > 0 ? 3 : 0, (value / max) * 100)}%` }}
              />
            </Tooltip>
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
  const [costSummary, setCostSummary] = useState<CostSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [budget, setBudget] = useState<number | null>(null);
  const [budgetInput, setBudgetInput] = useState<number | null>(null);
  const [savingBudget, setSavingBudget] = useState(false);
  const [spentThisMonth, setSpentThisMonth] = useState(0);
  const [budgetExceeded, setBudgetExceeded] = useState(false);
  // les deux tableaux peuvent vite compter des centaines de lignes - repliés
  // aux VISIBLE_ROWS plus recents par defaut (deja l'ordre du plus recent
  // au plus ancien, voir /logs cote serveur), avec un bouton pour tout
  // afficher plutot que de tronquer sans echappatoire.
  const [showAllModelCalls, setShowAllModelCalls] = useState(false);
  const [showAllToolCalls, setShowAllToolCalls] = useState(false);

  // n'appelle jamais setLoading() de facon synchrone (seulement dans les
  // callbacks .then()/.catch()/.finally()), pour pouvoir etre utilisee
  // telle quelle dans l'effet de montage ci-dessous : react-hooks
  // (set-state-in-effect) interdit d'appeler setState de facon synchrone
  // dans le corps d'un effet.
  function fetchLogs(): Promise<void> {
    return fetch(`${API_BASE}/logs`)
      .then((r) => (r.ok ? r.json() : []))
      .then((data: LogEvent[]) => { setEvents(data); })
      .catch(() => { setEvents([]); });
  }

  function fetchCostSummary(): Promise<void> {
    return fetch(`${API_BASE}/logs/cost_summary`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data: CostSummary | null) => { setCostSummary(data); })
      .catch(() => { setCostSummary(null); });
  }

  // seule source de verite pour "le budget est-il depasse" : le meme calcul
  // (current_month_cost() cote serveur) que celui sur lequel run_chat_stream/
  // dispatch_orchestrator bloquent reellement les nouveaux appels - un calcul
  // refait ici a partir des /logs bruts pourrait diverger (ex. en oubliant un
  // type d'evenement) de ce qui est vraiment applique.
  function fetchBudget(): Promise<void> {
    return fetch(`${API_BASE}/settings/budget/status`)
      .then((r) =>
        r.ok ? r.json() : { monthly_budget_usd: null, spent_usd: 0, exceeded: false },
      )
      .then((data: { monthly_budget_usd: number | null; spent_usd: number; exceeded: boolean }) => {
        setBudget(data.monthly_budget_usd);
        setBudgetInput(data.monthly_budget_usd);
        setSpentThisMonth(data.spent_usd);
        setBudgetExceeded(data.exceeded);
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
    loadAll();
  }

  function loadAll() {
    void Promise.all([fetchLogs(), fetchCostSummary(), fetchBudget()]).finally(() => {
      setLoading(false);
    });
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
      if (res.ok) {
        setBudget(budgetInput);
        void fetchBudget();
      }
    } finally {
      setSavingBudget(false);
    }
  }

  const modelCalls = useMemo(() => events.filter(isModelCall), [events]);
  const subagentModelCalls = useMemo(() => events.filter(isSubagentModelCall), [events]);
  const toolCalls = useMemo(() => events.filter(isToolCall), [events]);
  const visibleModelCalls = showAllModelCalls ? modelCalls : modelCalls.slice(0, VISIBLE_ROWS);
  const visibleToolCalls = showAllToolCalls ? toolCalls : toolCalls.slice(0, VISIBLE_ROWS);
  const costEvents = useMemo(
    () => [...modelCalls, ...subagentModelCalls],
    [modelCalls, subagentModelCalls],
  );

  const recentTotalTokens = useMemo(
    () => costEvents.reduce((sum, e) => sum + (e.total_tokens ?? 0), 0),
    [costEvents],
  );
  const recentTotalCost = useMemo(
    () => costEvents.reduce((sum, e) => sum + (e.cost_usd ?? 0), 0),
    [costEvents],
  );

  const recentDays = useDailyStats(costEvents);
  const totalCalls = costSummary?.total_calls ?? costEvents.length;
  const totalTokens = costSummary?.total_tokens ?? recentTotalTokens;
  const totalCost = costSummary?.total_cost_usd ?? recentTotalCost;
  const days = useMemo(
    () =>
      costSummary
        ? completeDailyStats(
            costSummary.by_day.map((day) => ({
              date: day.date,
              tokens: day.total_tokens,
              cost: day.cost_usd,
            })),
          )
        : recentDays,
    [costSummary, recentDays],
  );

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
          {e.total_tokens ?? 0} ({e.prompt_tokens}+{e.completion_tokens})
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

  const summaryModelColumns: TableColumn<ModelCostBreakdown>[] = [
    {
      key: "model",
      header: "Modèle",
      width: proportional(2),
      renderCell: (row) => <Text size="sm">{row.model}</Text>,
    },
    {
      key: "calls",
      header: "Appels",
      width: pixel(75),
      align: "end",
      renderCell: (row) => <Text size="sm">{row.calls}</Text>,
    },
    {
      key: "tokens",
      header: "Tokens",
      width: pixel(110),
      align: "end",
      renderCell: (row) => <Text size="sm">{row.total_tokens.toLocaleString("fr-FR")}</Text>,
    },
    {
      key: "cost",
      header: "Coût",
      width: pixel(85),
      align: "end",
      renderCell: (row) => <Text size="sm">{formatCost(row.cost_usd)}</Text>,
    },
  ];

  const summaryProjectColumns: TableColumn<ProjectCostBreakdown>[] = [
    {
      key: "project",
      header: "Projet",
      width: proportional(2),
      renderCell: (row) => <Text size="sm">{row.project_name}</Text>,
    },
    {
      key: "calls",
      header: "Appels",
      width: pixel(75),
      align: "end",
      renderCell: (row) => <Text size="sm">{row.calls}</Text>,
    },
    {
      key: "tokens",
      header: "Tokens",
      width: pixel(110),
      align: "end",
      renderCell: (row) => <Text size="sm">{row.total_tokens.toLocaleString("fr-FR")}</Text>,
    },
    {
      key: "cost",
      header: "Coût",
      width: pixel(85),
      align: "end",
      renderCell: (row) => <Text size="sm">{formatCost(row.cost_usd)}</Text>,
    },
  ];

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

      {!loading && events.length === 0 && totalCalls === 0 ? (
        <EmptyState
          title="Aucun log pour l'instant"
          description="Les appels au modèle et aux outils apparaîtront ici au fil des conversations."
        />
      ) : (
        <>
          {budgetExceeded && budget !== null && (
            <Banner
              status="warning"
              title="Budget mensuel dépassé"
              description={`${formatCost(spentThisMonth)} dépensés ce mois-ci, pour un budget de ${formatCost(budget)} - nouveaux messages bloqués jusqu'au mois prochain (ajuste-le ci-dessous pour continuer).`}
              className="mb-6"
            />
          )}

          <div className="mb-8 grid grid-cols-3 gap-3">
            <StatTile label="Appels modèle ce mois-ci" value={String(totalCalls)} />
            <StatTile label="Tokens ce mois-ci" value={totalTokens.toLocaleString("fr-FR")} />
            <StatTile label="Coût ce mois-ci" value={formatCost(totalCost)} />
          </div>

          {costSummary && costSummary.total_calls > 0 && (
            <div className="mb-8 grid grid-cols-1 gap-4 xl:grid-cols-2">
              <div>
                <Text size="sm" weight="semibold" className="mb-2 block">
                  Répartition mensuelle par modèle
                </Text>
                <div className="overflow-hidden rounded-xl border border-border">
                  <Table
                    data={costSummary.by_model}
                    columns={summaryModelColumns}
                    density="compact"
                    hasHover
                  />
                </div>
              </div>
              <div>
                <Text size="sm" weight="semibold" className="mb-2 block">
                  Répartition mensuelle par projet
                </Text>
                <div className="overflow-hidden rounded-xl border border-border">
                  <Table
                    data={costSummary.by_project}
                    columns={summaryProjectColumns}
                    density="compact"
                    hasHover
                  />
                </div>
              </div>
            </div>
          )}

          <div className="mb-8 grid grid-cols-1 gap-4 md:grid-cols-2">
            <DailyBarChart days={days} title="Tokens consommés par jour" getValue={(d) => d.tokens} />
            <DailyBarChart days={days} title="Coût par jour" getValue={(d) => d.cost} />
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
              Dépensé ce mois-ci : {formatCost(spentThisMonth)}
            </Text>
          </div>

          <div className="mb-2 flex items-center justify-between">
            <Text size="sm" weight="semibold">
              Appels au modèle
            </Text>
            {modelCalls.length > VISIBLE_ROWS && (
              <Button
                label={showAllModelCalls ? "Réduire" : `Tout afficher (${modelCalls.length})`}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowAllModelCalls((v) => !v);
                }}
              />
            )}
          </div>
          <div className="mb-8 overflow-hidden rounded-xl border border-border">
            <Table data={visibleModelCalls} columns={modelColumns} density="compact" hasHover />
          </div>

          <div className="mb-2 flex items-center justify-between">
            <Text size="sm" weight="semibold">
              Appels d'outils
            </Text>
            {toolCalls.length > VISIBLE_ROWS && (
              <Button
                label={showAllToolCalls ? "Réduire" : `Tout afficher (${toolCalls.length})`}
                variant="ghost"
                size="sm"
                onClick={() => {
                  setShowAllToolCalls((v) => !v);
                }}
              />
            )}
          </div>
          <div className="overflow-hidden rounded-xl border border-border">
            <Table data={visibleToolCalls} columns={toolColumns} density="compact" hasHover />
          </div>
        </>
      )}
    </div>
  );
}
