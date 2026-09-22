import { Text } from "@astryxdesign/core/Text";
import { ApiKeyField } from "./ApiKeySettings";

export function TavilySettings() {
  return (
    <div>
      <div className="mb-4 pr-8">
        <Text size="lg" weight="semibold" className="mb-1 block">
          Tavily
        </Text>
        <Text size="sm" color="secondary" className="block max-w-xl">
          Configure la clé utilisée en priorité par l'outil de recherche web.
        </Text>
      </div>

      <ApiKeyField
        title="Tavily (recherche web)"
        endpoint="/settings/tavily_key"
        placeholder="tvly-..."
        description={
          <>
            Clé{" "}
            <a
              href="https://app.tavily.com"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              Tavily
            </a>{" "}
            utilisée en priorité par l'outil de recherche web (résultats avec extraits de
            contenu, pas juste des liens). Optionnelle : sans elle, ou si les crédits sont
            épuisés, la recherche retombe automatiquement sur un scraping de DuckDuckGo.
          </>
        }
      />
    </div>
  );
}
