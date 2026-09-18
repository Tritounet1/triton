"""Rich-card tool calls: a conversation's way of saying "this specific
place/page deserves a visual card, not a plain text link" - the desktop
app recognizes these two tool names and renders a clickable card instead
of the usual collapsible tool-call row (see RichCard.tsx). No network I/O
happens here, only URL-building and validation: the actual navigation
(opening the URL in the OS browser) happens client-side. Read-only, and
outside enforce_project_sandbox's scope entirely - neither tool takes a
filesystem/process argument, so no project is required to use them."""

from urllib.parse import quote

from triton.tools._shared import Tool


def show_map(place: str = "", origin: str = "", destination: str = "") -> str:
    if origin and destination:
        url = (
            "https://www.google.com/maps/dir/?api=1"
            f"&origin={quote(origin)}&destination={quote(destination)}"
        )
        return f"Itinéraire affiché : {origin} → {destination}\n{url}"
    if place:
        url = f"https://www.google.com/maps/search/?api=1&query={quote(place)}"
        return f"Carte affichée pour « {place} »\n{url}"
    return "error: give either `place`, or both `origin` and `destination`"


def show_link_preview(url: str, title: str, description: str = "") -> str:
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    return f"Aperçu affiché : {title}\n{url}" + (f"\n{description}" if description else "")


REGISTRY: dict[str, Tool] = {
    "show_map": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "show_map",
                "description": "Displays an interactive map card in the chat UI, for a place "
                "or for directions between two points - opens Google Maps in the user's "
                "browser when clicked. Use this whenever the answer is fundamentally about a "
                "location (an address, a business, 'restaurants near X', a route from A to "
                "B) - a map card is far more useful there than describing the place in text. "
                "Give either `place` alone, or both `origin` and `destination`, never all "
                "three - don't guess an address that wasn't mentioned or found via "
                "web_search/fetch_url.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "place": {
                            "type": "string",
                            "description": "A place to search for and center the map on "
                            "(address, business name, or a query like 'restaurants in La "
                            "Rochelle'). Omit when giving origin/destination instead.",
                        },
                        "origin": {
                            "type": "string",
                            "description": "Starting point for directions - requires "
                            "`destination` too, and omit `place`.",
                        },
                        "destination": {
                            "type": "string",
                            "description": "End point for directions - requires `origin` too, "
                            "and omit `place`.",
                        },
                    },
                    "required": [],
                },
            },
        },
        fn=show_map,
        read_only=True,
    ),
    "show_link_preview": Tool(
        schema={
            "type": "function",
            "function": {
                "name": "show_link_preview",
                "description": "Displays a clickable preview card (title + optional "
                "description) for one specific web page in the chat UI, instead of a plain "
                "text link - opens the page in the user's browser when clicked. Use this to "
                "highlight a single page worth visiting (an article, a product page, a "
                "restaurant's own site...), not for a list of search results - `url` must be "
                "a real address already found via web_search or fetch_url, never guessed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string", "description": "The page's exact URL."},
                        "title": {
                            "type": "string",
                            "description": "Short title for the card (the page's own title, "
                            "not a generic label).",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional one-line summary of the page.",
                        },
                    },
                    "required": ["url", "title"],
                },
            },
        },
        fn=show_link_preview,
        read_only=True,
    ),
}
