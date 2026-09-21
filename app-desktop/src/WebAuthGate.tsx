import { useEffect, useState, type ReactNode, type SyntheticEvent } from "react";
import { API_BASE } from "./api";

interface WebAuthGateProps {
  children: ReactNode;
}

type AuthState = "checking" | "signed-out" | "signed-in";

export function WebAuthGate({ children }: WebAuthGateProps) {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    void fetch(`${API_BASE}/auth/session`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Impossible de vérifier la session.");
        const session = (await response.json()) as { authenticated: boolean };
        setAuthState(session.authenticated ? "signed-in" : "signed-out");
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Connexion au serveur impossible.");
        setAuthState("signed-out");
      });
  }, []);

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/auth/login`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        setError(response.status === 401 ? "Identifiants incorrects." : "Connexion impossible.");
        return;
      }
      setPassword("");
      setAuthState("signed-in");
    } catch {
      setError("Connexion au serveur impossible.");
    } finally {
      setSubmitting(false);
    }
  }

  if (authState === "signed-in") return <>{children}</>;

  return (
    <main className="flex h-full items-center justify-center bg-[var(--color-background)] p-6">
      <form
        className="w-full max-w-sm rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-lg"
        onSubmit={(event) => {
          void submit(event);
        }}
      >
        <h1 className="m-0 text-2xl font-semibold text-[var(--color-foreground)]">Triton</h1>
        <p className="mb-6 mt-2 text-sm text-[var(--color-muted-foreground)]">
          Connectez-vous pour accéder à votre espace de discussion.
        </p>
        <label className="mb-4 block text-sm font-medium text-[var(--color-foreground)]">
          Identifiant
          <input
            autoComplete="username"
            className="mt-1.5 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-[var(--color-foreground)]"
            disabled={submitting}
            onChange={(event) => {
              setUsername(event.target.value);
            }}
            required
            value={username}
          />
        </label>
        <label className="mb-4 block text-sm font-medium text-[var(--color-foreground)]">
          Mot de passe
          <input
            autoComplete="current-password"
            className="mt-1.5 w-full rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-3 py-2 text-[var(--color-foreground)]"
            disabled={submitting}
            onChange={(event) => {
              setPassword(event.target.value);
            }}
            required
            type="password"
            value={password}
          />
        </label>
        {error && <p className="mb-4 text-sm text-red-500">{error}</p>}
        <button
          className="w-full rounded-md bg-[var(--color-primary)] px-4 py-2 font-medium text-[var(--color-primary-foreground)] disabled:cursor-not-allowed disabled:opacity-60"
          disabled={submitting || authState === "checking"}
          type="submit"
        >
          {authState === "checking" ? "Vérification…" : submitting ? "Connexion…" : "Se connecter"}
        </button>
      </form>
    </main>
  );
}
