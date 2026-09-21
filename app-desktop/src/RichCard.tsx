import { openUrl } from "@tauri-apps/plugin-opener";
import { Text } from "@astryxdesign/core/Text";
import { LinkIcon, MapPinIcon } from "./icons";
import { type RichCardData } from "./richCardData";

export function RichCard({ card }: { card: RichCardData }) {
  return (
    <a
      href={card.url}
      target="_blank"
      rel="noreferrer"
      aria-label={`Ouvrir ${card.title} dans le navigateur`}
      onClick={(event) => {
        if ("__TAURI_INTERNALS__" in window) {
          event.preventDefault();
          void openUrl(card.url);
        }
      }}
      className="flex w-full items-start gap-3 rounded-xl border border-border bg-surface px-4 py-3 text-left transition-colors hover:border-accent"
    >
      <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent-muted text-accent">
        {card.kind === "map" ? (
          <MapPinIcon className="h-5 w-5" />
        ) : (
          <LinkIcon className="h-5 w-5" />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <Text weight="semibold" className="block truncate">
          {card.title}
        </Text>
        {card.subtitle && (
          <Text size="2xs" color="secondary" className="mt-0.5 block truncate">
            {card.subtitle}
          </Text>
        )}
        <Text size="2xs" color="secondary" className="mt-1 block truncate">
          {card.url}
        </Text>
      </div>
    </a>
  );
}
