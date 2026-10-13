import { Button } from "@astryxdesign/core/Button";
import { Dialog } from "@astryxdesign/core/Dialog";
import { Text } from "@astryxdesign/core/Text";
import { useState } from "react";
import { API_BASE } from "./api";

interface Model { id: string; name: string }
interface Result {
  model: string;
  content?: string;
  error?: string;
  duration_ms: number;
  cost_usd: number | null;
  tool_calls: number;
  total_tokens: number;
}

export function ModelComparisonModal({
  prompt,
  models,
  onClose,
  onChoose,
}: {
  prompt: string | null;
  models: Model[];
  onClose: () => void;
  onChoose: (model: string) => void;
}) {
  const [selected, setSelected] = useState<string[]>(() => models.slice(0, 2).map((model) => model.id));
  const [results, setResults] = useState<Result[] | null>(null);
  const [loading, setLoading] = useState(false);
  const toggle = (id: string) => {
    setSelected((current) => current.includes(id) ? current.filter((value) => value !== id) : current.length < 4 ? [...current, id] : current);
  };
  async function compare() {
    if (!prompt || selected.length < 2) return;
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE}/models/compare`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt, models: selected }) });
      setResults(response.ok ? (await response.json()) as Result[] : []);
    } finally { setLoading(false); }
  }
  return <Dialog isOpen={prompt !== null} onOpenChange={(open) => { if (!open) onClose(); }} purpose="info" width={960} aria-label="Comparer des modèles">
    <div className="flex max-h-[80vh] flex-col gap-4 p-6">
      <div><Text size="lg" weight="semibold">Comparer des modèles</Text><Text size="sm" color="secondary">Même prompt, jusqu’à quatre modèles. Les comparaisons n’exécutent pas d’outils.</Text></div>
      <div className="max-h-32 overflow-auto rounded-lg border border-border bg-surface-subtle p-3 text-sm">{prompt}</div>
      {!results && <div className="grid grid-cols-2 gap-2 overflow-auto">{models.map((model) => <label key={model.id} className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm"><input type="checkbox" checked={selected.includes(model.id)} onChange={() => { toggle(model.id); }} /> <span className="truncate">{model.name}</span></label>)}</div>}
      {results && <div className="grid min-h-0 grid-cols-2 gap-3 overflow-auto">{results.map((result) => <section key={result.model} className="flex min-w-0 flex-col gap-2 rounded-lg border border-border p-3"><Text weight="semibold" className="truncate">{result.model}</Text><Text size="2xs" color="secondary">{(result.duration_ms / 1000).toFixed(1)} s · {result.cost_usd === null ? "coût inconnu" : `$${result.cost_usd.toFixed(5)}`} · {result.total_tokens} tokens · {result.tool_calls} outil</Text><pre className="max-h-52 overflow-auto whitespace-pre-wrap text-xs">{result.error ?? result.content}</pre><Button label="Utiliser ce modèle" size="sm" variant="secondary" onClick={() => { onChoose(result.model); }} /></section>)}</div>}
      <div className="flex justify-end gap-2"><Button label="Fermer" variant="ghost" onClick={onClose} />{!results && <Button label="Comparer" variant="primary" isLoading={loading} isDisabled={selected.length < 2} onClick={() => { void compare(); }} />}</div>
    </div>
  </Dialog>;
}
