import type { ReactNode } from "react";
import { ClockIcon, CodeIcon, FlaskIcon, GlobeIcon } from "./icons";

interface Suggestion {
  title: string;
  description: string;
  prompt: string;
  icon: ReactNode;
  tone: string;
}

const PROJECT_SUGGESTIONS: Suggestion[] = [
  {
    title: "Explorer le dépôt",
    description: "Architecture, points d’entrée, dette",
    prompt: "Explore ce projet et résume son architecture, ses points d’entrée et sa dette technique.",
    icon: <CodeIcon className="h-4 w-4" />,
    tone: "bg-brand-muted text-brand-text",
  },
  {
    title: "Écrire des tests",
    description: "Couvrir les derniers changements",
    prompt: "Ajoute des tests de régression pour les derniers changements de ce projet.",
    icon: <FlaskIcon className="h-4 w-4" />,
    tone: "bg-success-muted text-success",
  },
];

const GENERAL_SUGGESTIONS: Suggestion[] = [
  {
    title: "Veille web",
    description: "Recherche et synthèse sourcée",
    prompt: "Fais une veille web sur ",
    icon: <GlobeIcon className="h-4 w-4" />,
    tone: "bg-warn-icon text-warn-text",
  },
  {
    title: "Planifier une tâche",
    description: "Exécution récurrente + résumé",
    prompt: "Aide-moi à planifier une tâche récurrente qui ",
    icon: <ClockIcon className="h-4 w-4" />,
    tone: "bg-[var(--color-background-purple)] text-[var(--color-text-purple)]",
  },
];

function greeting(date: Date): string {
  const hour = date.getHours();
  if (hour < 5 || hour >= 18) return "Bonsoir";
  return "Bonjour";
}

interface HomeHeroProps {
  projectName: string | null;
  onPick: (prompt: string) => void;
}

export function HomeHero({ projectName, onPick }: HomeHeroProps) {
  const suggestions = projectName
    ? [...PROJECT_SUGGESTIONS, ...GENERAL_SUGGESTIONS]
    : GENERAL_SUGGESTIONS;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col items-center gap-8 px-4 py-10 text-center">
      <div className="flex flex-col items-center gap-3">
        {projectName && (
          <span className="inline-flex items-center gap-2 rounded-full border border-line px-3 py-1 text-xs text-secondary">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            Projet {projectName}
          </span>
        )}
        <h1 className="m-0 text-3xl font-semibold tracking-tight text-primary sm:text-4xl">
          {greeting(new Date())}. On construit quoi ?
        </h1>
      </div>
      <div className="grid w-full grid-cols-[repeat(auto-fit,minmax(160px,190px))] justify-center gap-3">
        {suggestions.map((suggestion) => (
          <button
            key={suggestion.title}
            type="button"
            onClick={() => {
              onPick(suggestion.prompt);
            }}
            className="flex min-h-28 flex-col items-start gap-2.5 rounded-2xl border border-line bg-surface p-3.5 text-left transition-colors hover:border-[var(--color-border-emphasized)] hover:bg-muted focus-visible:outline-2 focus-visible:outline-brand"
          >
            <span className={`flex h-8 w-8 items-center justify-center rounded-lg ${suggestion.tone}`}>
              {suggestion.icon}
            </span>
            <span className="text-sm font-medium text-primary">{suggestion.title}</span>
            <span className="text-xs text-secondary">{suggestion.description}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
