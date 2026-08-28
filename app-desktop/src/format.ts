export function formatArgs(args: Record<string, unknown>): string {
  return Object.entries(args)
    .map(([k, v]) => {
      if (k === "content" && typeof v === "string") {
        return `${k}=<${v.length} caractères>`;
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
