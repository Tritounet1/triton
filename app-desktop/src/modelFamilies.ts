// Regroupement des modeles OpenRouter par fournisseur, partage entre
// ModelPage.tsx (liste groupee) et App.tsx (avatar du modele actif dans le
// chat) : la famille est deduite du prefixe avant le "/" de l'id OpenRouter
// (ex. "anthropic/claude-..."), deja donne par l'API, pas besoin de le
// deviner autrement. Logo reel pour les familles qui en ont un (public/*.png)
// - voir PLAN.md pour la liste de celles qui restent a faire - toute autre
// famille (connue ou non) retombe sur public/default-logo.png, pas les
// initiales.

export interface FamilyInfo {
  label: string;
  logo?: string;
}

const DEFAULT_LOGO = "/default-logo.png";

export const FAMILIES: Record<string, FamilyInfo> = {
  anthropic: { label: "Anthropic (Claude)", logo: "/anthropic-logo.png" },
  openai: { label: "OpenAI (ChatGPT)", logo: "/chatgpt-logo.png" },
  google: { label: "Google (Gemini)", logo: "/gemini-logo.png" },
  qwen: { label: "Qwen (Alibaba)", logo: "/qwen-logo.png" },
  "meta-llama": { label: "Meta (Llama)", logo: "/llama-logo.png" },
  mistralai: { label: "Mistral AI", logo: "/mistral-logo.png" },
  "x-ai": { label: "xAI (Grok)", logo: "/x-logo.png" },
  deepseek: { label: "DeepSeek", logo: "/deepseek-logo.png" },
  "z-ai": { label: "Z.ai (GLM)", logo: "/zai-logo.png" },
  cohere: { label: "Cohere" },
  amazon: { label: "Amazon (Nova)" },
  nvidia: { label: "NVIDIA (Nemotron)" },
  perplexity: { label: "Perplexity" },
  minimax: { label: "MiniMax" },
  moonshotai: { label: "Moonshot AI (Kimi)", logo: "/kimi-logo.png" },
  microsoft: { label: "Microsoft" },
};

// prefixes OpenRouter differents pour une meme famille (ex. "meta" et
// "meta-llama" designent tous les deux Meta) : normalises vers une seule
// cle canonique avant recherche, sinon "meta" ne retrouverait pas l'entree
// enregistree sous "meta-llama"
const FAMILY_ALIASES: Record<string, string> = {
  meta: "meta-llama",
};

export function familyKey(id: string): string {
  const prefix = id.replace(/^~/, "").split("/")[0] ?? "";
  const canonical = FAMILY_ALIASES[prefix] ?? prefix;
  return canonical in FAMILIES ? canonical : "other";
}

export function familyInfo(key: string): FamilyInfo {
  const info = FAMILIES[key] ?? { label: "Autres" };
  return { ...info, logo: info.logo ?? DEFAULT_LOGO };
}

/** Nom + logo a passer a un composant Avatar pour representer le modele
 * actuellement selectionne (toujours un logo - default-logo.png si la
 * famille n'en a pas de propre, ou si aucun modele n'est encore connu). */
export function modelAvatar(modelId: string | null): { name: string; logo?: string } {
  if (!modelId) return { name: "?", logo: DEFAULT_LOGO };
  const info = familyInfo(familyKey(modelId));
  return { name: info.label, logo: info.logo };
}
