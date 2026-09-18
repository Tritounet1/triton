// Type + fonction pure pour RichCard.tsx - extrait dans son propre fichier
// (nom volontairement different de RichCard.tsx au-dela de la casse : sur
// un systeme de fichiers insensible a la casse (macOS/APFS par defaut),
// richCard.ts et RichCard.tsx designent le meme fichier) pour que
// RichCard.tsx n'exporte qu'un composant (voir react-refresh/
// only-export-components), meme raison que chatMessages.ts.

export interface RichCardData {
  kind: "map" | "link";
  title: string;
  subtitle?: string;
  url: string;
}

/** Reconnait un appel a show_map/show_link_preview (voir
 * triton/tools/cards.py) et construit ce qu'il faut pour rendre une carte
 * a la place de la ligne de tool-call habituelle - retourne null pour
 * tout autre outil (y compris un show_map/show_link_preview aux
 * arguments incomplets), pour que l'appelant retombe alors sur le rendu
 * generique (ChatToolCalls). L'URL est reconstruite ici plutot que lue
 * dans le resultat texte de l'outil : les arguments sont deja structures,
 * pas besoin de re-parser une chaine. */
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
