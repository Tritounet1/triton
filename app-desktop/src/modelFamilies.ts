// Regroupement des modeles OpenRouter par fournisseur, partage entre
// ModelPage.tsx (liste groupee) et App.tsx (avatar du modele actif dans le
// chat) : la famille est deduite du prefixe avant le "/" de l'id OpenRouter
// (ex. "anthropic/claude-..."), deja donne par l'API, pas besoin de le
// deviner autrement. Logos reels pour les plus connus (public/*.svg), le
// reste retombe sur les initiales via le composant Avatar.

export interface FamilyInfo {
  label: string;
  logo?: string;
}

export const FAMILIES: Record<string, FamilyInfo> = {
  anthropic: { label: "Anthropic (Claude)", logo: "/claude-logo.svg" },
  openai: { label: "OpenAI (ChatGPT)", logo: "/openai-logo.svg" },
  google: { label: "Google (Gemini)", logo: "/gemini-logo.svg" },
  qwen: { label: "Qwen (Alibaba)", logo: "/qwen-logo.svg" },
  "meta-llama": { label: "Meta (Llama)", logo: "/meta-logo.svg" },
  mistralai: { label: "Mistral AI", logo: "/mistral-logo.svg" },
  "x-ai": { label: "xAI (Grok)" },
  deepseek: { label: "DeepSeek" },
  "z-ai": { label: "Z.ai (GLM)" },
  cohere: { label: "Cohere" },
  amazon: { label: "Amazon (Nova)" },
  nvidia: { label: "NVIDIA (Nemotron)" },
  perplexity: { label: "Perplexity" },
  minimax: { label: "MiniMax" },
  moonshotai: { label: "Moonshot AI (Kimi)" },
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
  return FAMILIES[key] ?? { label: "Autres" };
}

/** Nom + logo a passer a un composant Avatar pour representer le modele
 * actuellement selectionne (fallback sur les initiales du nom si la
 * famille n'a pas de logo connu, ou si aucun modele n'est encore connu). */
export function modelAvatar(modelId: string | null): { name: string; logo?: string } {
  if (!modelId) return { name: "?" };
  const info = familyInfo(familyKey(modelId));
  return { name: info.label, logo: info.logo };
}
