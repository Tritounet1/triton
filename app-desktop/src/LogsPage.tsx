import { useEffect, useMemo, useState } from "react";
import { Text } from "@astryxdesign/core/Text";
import { Badge } from "@astryxdesign/core/Badge";
import { IconButton } from "@astryxdesign/core/IconButton";
import { Table, proportional, pixel, type TableColumn } from "@astryxdesign/core/Table";
import { EmptyState } from "@astryxdesign/core/EmptyState";
import { ArrowLeftIcon, ChartBarIcon, RefreshIcon } from "./icons";
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

type LogEvent = ModelCallEvent | ToolCallEvent;

function isModelCall(e: LogEvent): e is ModelCallEvent {
  return e.type === "model_call";
}

function isToolCall(e: LogEvent): e is ToolCallEvent {
  return e.type === "tool_call";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString("fr-FR");
}

function toolFailed(result: string): boolean {
  return result.startsWith("erreur") || result.startsWith("action refusée");
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

interface DayTokens {
  date: string;
  tokens: number;
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

function useDailyTokens(modelCalls: ModelCallEvent[]): DayTokens[] {
  return useMemo(() => {
    if (modelCalls.length === 0) return [];

    const byDay = new Map<string, number>();
    for (const e of modelCalls) {
      const key = toDayKey(e.timestamp);
      byDay.set(key, (byDay.get(key) ?? 0) + e.total_tokens);
    }

    // comble les jours sans appel (barre a 0) pour un axe continu, du plus
    // ancien jour observe jusqu'a aujourd'hui, puis ne garde que les
    // CHART_DAYS derniers jours
    const earliest = [...byDay.keys()].sort()[0];
    if (!earliest) return [];
    const days: DayTokens[] = [];
    for (
      let d = new Date(earliest);
      d <= new Date();
      d.setDate(d.getDate() + 1)
    ) {
      const key = d.toISOString().slice(0, 10);
      days.push({ date: key, tokens: byDay.get(key) ?? 0 });
    }
    return days.slice(-CHART_DAYS);
  }, [modelCalls]);
}

interface TokensBarChartProps {
  modelCalls: ModelCallEvent[];
}

function TokensBarChart({ modelCalls }: TokensBarChartProps) {
  const days = useDailyTokens(modelCalls);
  if (days.length === 0) return null;

  const max = Math.max(1, ...days.map((d) => d.tokens));

  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-4">
      <Text size="2xs" color="secondary" className="mb-3 block uppercase tracking-wide">
        Tokens consommés par jour
      </Text>
      <div className="flex items-end gap-1.5" style={{ height: CHART_HEIGHT_PX }}>
        {days.map((d) => (
          <div
            key={d.date}
            title={`${formatDayLabel(d.date)} : ${d.tokens.toLocaleString("fr-FR")} tokens`}
            className="flex-1 rounded-t bg-accent transition-[height] hover:opacity-80"
            style={{ height: `${Math.max(d.tokens > 0 ? 3 : 0, (d.tokens / max) * 100)}%` }}
          />
        ))}
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

interface LogsPageProps {
  onBack: () => void;
}

export function LogsPage({ onBack }: LogsPageProps) {
  const [events, setEvents] = useState<LogEvent[]>([]);
  const [loading, setLoading] = useState(true);

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

  // pour le bouton "rafraichir" : la remise a `true` de loading doit rester
  // synchrone (affichage immediat du spinner), ce qui est permis dans un
  // gestionnaire d'evenement (juste pas dans un effet).
  function refresh() {
    setLoading(true);
    fetchLogs();
  }

  useEffect(fetchLogs, []);

  const modelCalls = useMemo(() => events.filter(isModelCall), [events]);
  const toolCalls = useMemo(() => events.filter(isToolCall), [events]);

  const totalTokens = useMemo(
    () => modelCalls.reduce((sum, e) => sum + e.total_tokens, 0),
    [modelCalls],
  );

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

  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <IconButton
            label="Retour"
            icon={<ArrowLeftIcon />}
            variant="ghost"
            size="sm"
            onClick={onBack}
          />
          <div className="flex items-center gap-2">
            <ChartBarIcon className="h-5 w-5 text-secondary" />
            <Text size="lg" weight="semibold">
              Historique des logs
            </Text>
          </div>
        </div>
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
          <div className="mb-8 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatTile label="Appels modèle" value={String(modelCalls.length)} />
            <StatTile label="Tokens totaux" value={totalTokens.toLocaleString("fr-FR")} />
            <StatTile label="Appels d'outils" value={String(toolCalls.length)} />
            <StatTile label="Outil le plus utilisé" value={topTool ? topTool[0] : "-"} />
          </div>

          <div className="mb-8">
            <TokensBarChart modelCalls={modelCalls} />
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
