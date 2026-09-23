// Type + pure function for RichCard.tsx - extracted into its own file
// (deliberately named differently from RichCard.tsx beyond case: on a
// case-insensitive filesystem (macOS/APFS by default), richCard.ts and
// RichCard.tsx would refer to the same file) so RichCard.tsx only exports a
// component (see react-refresh/only-export-components), same reason as
// chatMessages.ts.

export interface RichCardData {
  kind: "map" | "link";
  title: string;
  subtitle?: string;
  url: string;
}

/** Recognizes a show_map/show_link_preview call (see triton/tools/cards.py)
 * and builds what's needed to render a card instead of the usual tool-call
 * line - returns null for any other tool (including a show_map/
 * show_link_preview with incomplete arguments), so the caller falls back to
 * the generic rendering (ChatToolCalls). The URL is rebuilt here rather
 * than read from the tool's text result: the arguments are already
 * structured, no need to re-parse a string. */
export function richCardFromToolCall(
  tool: string,
  args: Record<string, unknown>,
): RichCardData | null {
  const str = (key: string): string => {
    const value = args[key];
    return typeof value === "string" ? value : "";
  };

  if (tool === "show_map") {
    const origin = str("origin");
    const destination = str("destination");
    if (origin && destination) {
      return {
        kind: "map",
        title: "Itinéraire",
        subtitle: `${origin} → ${destination}`,
        url:
          "https://www.google.com/maps/dir/?api=1" +
          `&origin=${encodeURIComponent(origin)}&destination=${encodeURIComponent(destination)}`,
      };
    }
    const place = str("place");
    if (place) {
      return {
        kind: "map",
        title: place,
        url: `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(place)}`,
      };
    }
    return null;
  }

  if (tool === "show_link_preview") {
    const url = str("url");
    if (!url) return null;
    return {
      kind: "link",
      title: str("title") || url,
      subtitle: str("description") || undefined,
      url,
    };
  }

  return null;
}
