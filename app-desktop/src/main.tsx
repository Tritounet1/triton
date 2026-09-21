import React from "react";
import ReactDOM from "react-dom/client";
import { invoke } from "@tauri-apps/api/core";
import { API_BASE, isTauri } from "./api";
import App from "./App";
import { ErrorBoundary } from "./ErrorBoundary";

const rootElement = document.getElementById("root");
if (!rootElement) throw new Error("index.html doit contenir un element #root");
const appRoot: HTMLElement = rootElement;

const LOCAL_API_TOKEN_HEADER = "X-Triton-Local-Token";

function renderApp() {
  ReactDOM.createRoot(appRoot).render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>,
  );
}

function installLocalApiToken(token: string) {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
    const url = input instanceof Request ? input.url : input instanceof URL ? input.href : input;
    if (!url.startsWith(`${API_BASE}/`)) return nativeFetch(input, init);

    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set(LOCAL_API_TOKEN_HEADER, token);
    return nativeFetch(input, { ...init, headers });
  };
}

async function waitForLocalApiToken(): Promise<string> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const token = await invoke<string | null>("local_api_token");
    if (token) return token;
    await new Promise((resolve) => window.setTimeout(resolve, 50));
  }
  throw new Error("Le serveur local Triton n'a pas demarre de maniere securisee.");
}

async function bootstrap() {
  if (isTauri && !import.meta.env.DEV) installLocalApiToken(await waitForLocalApiToken());
  renderApp();
}

void bootstrap().catch((error: unknown) => {
  appRoot.textContent = error instanceof Error ? error.message : "Demarrage de Triton impossible.";
});
