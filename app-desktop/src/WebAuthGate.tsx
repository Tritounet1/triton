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
  const [showPassword, setShowPassword] = useState(false);

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

  const fieldClass =
    "h-11 w-full rounded-[10px] border border-[var(--triton-line-strong)] bg-[var(--triton-surface)] px-3 text-[15px] text-[var(--triton-ink)] outline-none transition-shadow focus:border-[var(--triton-brand)] focus:shadow-[0_0_0_4px_var(--triton-brand-muted)] disabled:opacity-60";

  return (
    <div className="flex h-full flex-wrap overflow-x-hidden overflow-y-auto bg-[var(--triton-surface)] font-sans text-[var(--triton-ink)]">
      <section
        aria-label="Présentation"
        className="flex min-h-[320px] min-w-0 max-w-full flex-[1_1_480px] flex-col justify-between gap-12 bg-[#0b1018] p-8 text-[#e6ebf2] sm:p-12"
      >
        <div className="flex items-center gap-3">
          <img src="/default-logo.png" alt="" className="h-10 w-10 rounded-[11px] object-cover" />
          <span className="text-xl font-semibold">Triton</span>
        </div>
        <div className="flex max-w-[520px] flex-col gap-7">
          <h1 className="m-0 text-4xl font-semibold leading-tight tracking-tight sm:text-[44px]">
            Ton agent, ton serveur, ton workspace.
          </h1>
          <div
            aria-hidden="true"
            className="flex flex-col rounded-2xl border border-[#222d3f] bg-[#111824] p-4 font-mono text-[13px] leading-[1.9] text-[#8a96a8]"
          >
            <span>
              › read_file <span className="text-[#c9d2de]">src/triton/agent.py</span>
            </span>
            <span>
              › search <span className="text-[#c9d2de]">"tool_call"</span>
            </span>
            <span>
              › edit_file <span className="text-[#c9d2de]">agent.py</span>{" "}
              <span className="text-[#3dd68c]">+8</span> <span className="text-[#f28b82]">−2</span>
            </span>
            <span>
              › run_tests <span className="text-[#3dd68c]">OK</span>
            </span>
          </div>
        </div>
        <span className="text-xs text-[#8a96a8]">
          Instance auto-hébergée · les fichiers restent dans le runner isolé
        </span>
      </section>

      <main className="flex min-w-0 max-w-full flex-[1_1_420px] items-center justify-center px-6 py-12">
        <form
          className="flex w-full max-w-[360px] flex-col gap-5"
          onSubmit={(event) => {
            void submit(event);
          }}
        >
          <div className="flex flex-col gap-1.5">
            <h2 className="m-0 text-[26px] font-semibold tracking-tight">Connexion</h2>
            <p className="m-0 text-sm text-[var(--triton-ink-secondary)]">
              Connecte-toi pour accéder à ton espace Triton.
            </p>
          </div>
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Identifiant
            <input
              autoComplete="username"
              className={fieldClass}
              disabled={submitting}
              onChange={(event) => {
                setUsername(event.target.value);
              }}
              required
              value={username}
            />
          </label>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="triton-password" className="text-[13px] font-medium">
              Mot de passe
            </label>
            <div className="relative">
              <input
                id="triton-password"
                autoComplete="current-password"
                className={`${fieldClass} pr-11`}
                disabled={submitting}
                onChange={(event) => {
                  setPassword(event.target.value);
                }}
                required
                type={showPassword ? "text" : "password"}
                value={password}
              />
              <button
                type="button"
                aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                aria-pressed={showPassword}
                className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-lg text-[var(--triton-ink-secondary)] hover:bg-[var(--triton-raised)]"
                onClick={() => {
                  setShowPassword((visible) => !visible);
                }}
              >
                <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" aria-hidden="true">
                  <path
                    d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12Z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                  <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.8" />
                </svg>
              </button>
            </div>
          </div>
          {error && (
            <p role="alert" className="m-0 rounded-lg bg-[var(--color-error-muted,#fdecec)] px-3 py-2 text-sm text-[light-dark(#b42318,#ffb4a9)]">
              {error}
            </p>
          )}
          <button
            className="flex h-[46px] w-full items-center justify-center gap-2 rounded-[11px] bg-[var(--triton-ink)] text-[15px] font-medium text-[var(--triton-surface)] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
            disabled={submitting || authState === "checking"}
            type="submit"
          >
            {authState === "checking" ? "Vérification…" : submitting ? "Connexion…" : "Se connecter"}
          </button>
          <p className="m-0 flex items-center gap-2 border-t border-[var(--triton-line)] pt-3 text-xs text-[var(--triton-ink-secondary)]">
            <svg viewBox="0 0 24 24" fill="none" className="h-3.5 w-3.5" aria-hidden="true">
              <rect x="4" y="11" width="16" height="10" rx="2" stroke="currentColor" strokeWidth="2" />
              <path d="M8 11V7a4 4 0 0 1 8 0v4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            Cookie de session sécurisé
          </p>
        </form>
      </main>
    </div>
  );
}
