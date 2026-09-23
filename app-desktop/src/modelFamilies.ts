// Groups OpenRouter models by provider, shared between ModelPage.tsx
// (grouped list) and App.tsx (active model's avatar in chat): the family is
// derived from the prefix before the "/" in the OpenRouter id (e.g.
// "anthropic/claude-..."), already given by the API, no need to guess it
// otherwise. Real logo for families that have one (public/*.png) - see
// PLAN.md for the list of ones still to do - any other family (known or
// not) falls back to public/default-logo.png, not initials.

export interface FamilyInfo {
  label: string;
  logo?: string;
}

const DEFAULT_LOGO = "/default-logo.png";

// Families deliberately absent from model selectors: still known here to
// correctly display a model already saved (avatar, logs, etc.), but not
// offered in the picker UI.
const HIDDEN_MODEL_FAMILIES = new Set([
  "cohere",
  "amazon",
  "nvidia",
  "perplexity",
  "minimax",
  "microsoft",
  "other",
]);

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
  microsoft: { label: "Microsoft", logo: "/microsoft-logo.png" },
  xiaomi: { label: "Xiaomi (MiMo)", logo: "/xiaomi-logo.png" },
};

// different OpenRouter prefixes for the same family (e.g. "meta" and
// "meta-llama" both mean Meta): normalized to a single canonical key before
// lookup, otherwise "meta" wouldn't find the entry stored under
// "meta-llama"
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

/** Whether a model's family is part of the selection deliberately exposed in
 * settings. Shared by the main model and roles so their catalogs stay
 * strictly consistent. */
export function isModelFamilyVisible(modelId: string): boolean {
  return !HIDDEN_MODEL_FAMILIES.has(familyKey(modelId));
}

/** Name + logo to pass to an Avatar component to represent the currently
 * selected model (always a logo - default-logo.png if the family has none
 * of its own, or if no model is known yet). */
export function modelAvatar(modelId: string | null): {
  name: string;
  logo?: string;
} {
  if (!modelId) return { name: "?", logo: DEFAULT_LOGO };
  const info = familyInfo(familyKey(modelId));
  return { name: info.label, logo: info.logo };
}
