const MAX_ARG_PREVIEW = 200;

export function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => {
      if (typeof v === "string" && v.length > MAX_ARG_PREVIEW) {
        const preview = v.slice(0, MAX_ARG_PREVIEW).replace(/\n/g, " ");
        return `${k}="${preview}..." (${v.length} caractères)`;
      }
      return `${k}=${JSON.stringify(v)}`;
    })
    .join(", ");
}

export function formatDuration(seconds: number | undefined): string {
  if (seconds === undefined) return "-";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  return `${seconds.toFixed(2)}s`;
}
