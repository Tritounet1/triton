export const isTauri =
  typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

const configuredApiBase = import.meta.env.VITE_TRITON_API_BASE?.replace(/\/$/, "");

export const API_BASE =
  configuredApiBase ??
  (isTauri || import.meta.env.DEV ? "http://127.0.0.1:8000" : "");
