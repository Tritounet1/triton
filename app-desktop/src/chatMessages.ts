// Types et fonctions pures pour transformer l'historique brut d'une session
// (RawSessionMessage[], tel que renvoye par le serveur) en messages de chat
// prets a rendre (ChatMsg[]) - extrait de App.tsx pour que ce fichier
// n'exporte que des non-composants (voir react-refresh/only-export-
// components) et pour pouvoir les tester unitairement sans monter tout
// App.tsx (voir chatMessages.test.ts).
import { formatArgs } from "./format";

export interface SentFile {
  name: string;
  dataUrl: string;
}

export interface MultiAgentSubtaskToolCall {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

export type ChatMsg =
  | { kind: "user"; text: string; time: number; images?: string[]; files?: SentFile[] }
  | { kind: "assistant"; text: string; time: number; model?: string }
  | {
      kind: "tool";
      // presente seulement pour une sous-tache multi-agent en direct
      // (voir dispatchMultiAgent) : permet de mettre a jour la meme entree
      // au lieu d'en empiler une nouvelle a chaque sondage.
      id?: string;
      tool: string;
      args: Record<string, unknown>;
      result: string;
      time: number;
      // modele qui a demande cet appel d'outil ; utile lorsqu'un tour se
      // termine avant d'avoir produit une reponse textuelle finale.
      model?: string;
      // statut explicite pour une sous-tache multi-agent en direct (connu
      // sans avoir a l'inferer du texte, contrairement a un vrai appel
      // d'outil deja termine - voir toolCallStatus).
      status?: "pending" | "running" | "complete" | "error";
      // presents seulement pour une sous-tache multi-agent : sa description
      // (le "target" de sa propre ligne) et les outils qu'elle a deja
      // appeles, mis a jour en direct pendant qu'elle tourne (voir
      // pollMultiAgentRun / multiAgentSubtaskDetail).
      subtaskDescription?: string;
      subtaskToolCalls?: MultiAgentSubtaskToolCall[];
    }
  | { kind: "info"; text: string; time: number }
  | { kind: "error"; text: string; time: number };

export interface ContentPart {
  type: "text" | "image_url" | "file";
  text?: string;
  image_url?: { url: string };
  file?: { filename: string; file_data: string };
}

export interface RawSessionMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string | ContentPart[] | null;
  tool_call_id?: string;
  tool_calls?: { id: string; function: { name: string; arguments: string } }[];
  model?: string;
}

/** Un message utilisateur enregistre peut etre soit une simple chaine, soit
 * une liste de parts (texte + images/fichiers) des qu'une piece jointe a ete
 * envoyee (voir build_user_content cote serveur). */
export function extractUserContent(content: string | ContentPart[]): {
  text: string;
  images: string[];
  files: SentFile[];
} {
  if (typeof content === "string") return { text: content, images: [], files: [] };
  const text = content
    .filter((p) => p.type === "text")
    .map((p) => p.text ?? "")
    .join("\n");
  const images = content
    .filter((p) => p.type === "image_url" && p.image_url?.url)
    .map((p) => p.image_url?.url ?? "");
  const files = content
    .filter((p) => p.type === "file" && p.file?.file_data)
    .map((p) => ({ name: p.file?.filename ?? "document.pdf", dataUrl: p.file?.file_data ?? "" }));
  return { text, images, files };
}

export function isPdfDataUrl(dataUrl: string): boolean {
  return dataUrl.startsWith("data:application/pdf");
}

/** Meme convention que server.py's truncate_before_turn : coupe `msgs` juste
 * avant le message utilisateur qui demarre `turnIndex` (1-based), pour que
 * l'affichage local reflete immediatement ce que edit_turn_index va faire
 * cote serveur (pas d'attente du prochain evenement SSE pour voir
 * disparaitre les anciens tours). turnIndex introuvable (deja hors bornes) :
 * no-op, retourne msgs tel quel. */
export function truncateBeforeTurn(msgs: ChatMsg[], turnIndex: number): ChatMsg[] {
  let count = 0;
  for (let i = 0; i < msgs.length; i++) {
    if (msgs[i]?.kind === "user") {
      count += 1;
      if (count === turnIndex) return msgs.slice(0, i);
    }
  }
  return msgs;
}

/** Le message utilisateur qui demarre `turnIndex` (1-based) - utilise par
 * "regenerer" pour retrouver le texte/pieces jointes du tour a renvoyer
 * tel quel. */
export function userMessageAtTurn(
  msgs: ChatMsg[],
  turnIndex: number,
): Extract<ChatMsg, { kind: "user" }> | undefined {
  let count = 0;
  for (const m of msgs) {
    if (m.kind === "user") {
      count += 1;
      if (count === turnIndex) return m;
    }
  }
  return undefined;
}

/** id de session au format 2026-08-28_101500 -> "28/08/2026 10:15" */
export function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$/.exec(id);
  if (!m) return id;
  const [, y = "", mo = "", d = "", h = "", mi = ""] = m;
  return `${d}/${mo}/${y} ${h}:${mi}`;
}

export function historyToMessages(raw: RawSessionMessage[]): ChatMsg[] {
  const out: ChatMsg[] = [];
  const now = Date.now();

  for (const m of raw) {
    if (m.role === "user" && m.content) {
      const { text, images, files } = extractUserContent(m.content);
      out.push({
        kind: "user",
        text,
        time: now,
        images: images.length ? images : undefined,
        files: files.length ? files : undefined,
      });
    } else if (m.role === "assistant") {
      for (const toolCall of m.tool_calls ?? []) {
        const args = JSON.parse(toolCall.function.arguments || "{}") as Record<
          string,
          unknown
        >;
        const toolResult = raw.find(
          (x) => x.role === "tool" && x.tool_call_id === toolCall.id,
        );
        out.push({
          kind: "tool",
          tool: toolCall.function.name,
          args,
          // le contenu d'un message "tool" (resultat d'un appel d'outil)
          // est toujours une chaine simple - seul un message "user" peut
          // contenir une liste de parts (texte + images, voir
          // extractUserContent), d'ou la garde meme si le type partage est
          // plus large.
          result: typeof toolResult?.content === "string" ? toolResult.content : "",
          time: now,
          model: m.model,
        });
      }
      if (typeof m.content === "string" && m.content) {
        out.push({
          kind: "assistant",
          text: m.content,
          time: now,
          model: m.model,
        });
      }
    }
  }

  return out;
}

export type AssistantMsg = Extract<ChatMsg, { kind: "assistant" }>;
export type ToolMsg = Extract<ChatMsg, { kind: "tool" }>;

export type RenderGroup =
  // turnIndex : le meme "1-based nth user message" que turn_index_of cote
  // serveur (voir server.py) - c'est ce qu'edit_turn_index attend, donc
  // calcule ici une bonne fois plutot que recompte a chaque clic sur
  // "modifier".
  | { type: "user"; msg: Extract<ChatMsg, { kind: "user" }>; turnIndex: number }
  | { type: "system"; msg: Extract<ChatMsg, { kind: "info" | "error" }> }
  // precedingTurnIndex : le tour utilisateur qui a produit ce groupe -
  // c'est ce que "regenerer" renvoie comme edit_turn_index pour redemander
  // exactement la meme reponse.
  | { type: "assistant"; items: (AssistantMsg | ToolMsg)[]; precedingTurnIndex: number };

/** Regroupe les messages consécutifs d'assistant/outil sous un seul avatar
 * (comme un vrai fil de discussion), plutôt qu'un avatar répété à chaque
 * morceau de la réponse. */
export function groupMessages(msgs: ChatMsg[]): RenderGroup[] {
  const groups: RenderGroup[] = [];
  let turnIndex = 0;
  for (const m of msgs) {
    if (m.kind === "user") {
      turnIndex += 1;
      groups.push({ type: "user", msg: m, turnIndex });
    } else if (m.kind === "info" || m.kind === "error") {
      groups.push({ type: "system", msg: m });
    } else {
      const last = groups[groups.length - 1];
      if (last?.type === "assistant") {
        last.items.push(m);
      } else if (
        // Un message d'information peut arriver entre deux etapes d'un
        // meme tour (par exemple le point de restauration cree juste avant
        // une ecriture). Il ne doit pas faire reapparaitre un deuxieme
        // avatar pour la meme reponse ; on le conserve visuellement apres
        // le groupe, mais rattache la suite a l'assistant precedent.
        last?.type === "system" &&
        last.msg.kind === "info" &&
        groups[groups.length - 2]?.type === "assistant"
      ) {
        const previousAssistant = groups[groups.length - 2];
        if (previousAssistant?.type === "assistant") previousAssistant.items.push(m);
      } else {
        groups.push({ type: "assistant", items: [m], precedingTurnIndex: turnIndex });
      }
    }
  }
  return groups;
}

/** Le modele connu le plus recent d'une reponse groupee. Les anciens
 * historiques pouvaient ne pas enregistrer le modele sur les fragments
 * intermediaires autour d'un appel d'outil, alors que sa reponse finale le
 * contient bien. */
export function assistantGroupModel(items: (AssistantMsg | ToolMsg)[]): string | undefined {
  return [...items].reverse().find((item) => Boolean(item.model))?.model;
}

export type Block =
  { kind: "tools"; items: ToolMsg[] } | { kind: "text"; msg: AssistantMsg };

/** Dans un groupe assistant, fusionne les appels d'outils consécutifs en un
 * seul ChatToolCalls (résumé repliable natif si plusieurs), sépare le texte. */
export function toBlocks(items: (AssistantMsg | ToolMsg)[]): Block[] {
  const blocks: Block[] = [];
  for (const item of items) {
    if (item.kind === "tool") {
      const last = blocks[blocks.length - 1];
      if (last?.kind === "tools") {
        last.items.push(item);
      } else {
        blocks.push({ kind: "tools", items: [item] });
      }
    } else {
      blocks.push({ kind: "text", msg: item });
    }
  }
  return blocks;
}

/** "mcp__server-name__tool_name" -> { label: "tool_name", server:
 * "server-name" } (voir mcp_client.py's tool_key/MCP_PREFIX cote serveur) ;
 * un outil natif (write_file, run_shell...) n'a pas ce prefixe -> pas de
 * serveur. Utilise pour le style "Claude souhaite utiliser X de Y" de la
 * demande d'autorisation. */
export function parseToolDisplay(toolName: string): { label: string; server: string | null } {
  if (!toolName.startsWith("mcp__")) return { label: toolName, server: null };
  const rest = toolName.slice("mcp__".length);
  const sepIndex = rest.indexOf("__");
  if (sepIndex === -1) return { label: rest, server: null };
  return { label: rest.slice(sepIndex + 2), server: rest.slice(0, sepIndex) };
}

export function toolCallStatus(result: string): "complete" | "error" {
  return result.startsWith("error") || result.startsWith("action denied")
    ? "error"
    : "complete";
}

export interface EditFileEdit {
  path: string;
  old_string: string;
  new_string: string;
}

/** edit_file accepte desormais plusieurs hunks/fichiers en un seul appel
 * (voir filesystem.py) : ses arguments sont `{edits: [{path, old_string,
 * new_string, replace_all?}, ...]}` plutot que old_string/new_string a
 * plat. Le modele n'est pas force de respecter le schema (voir
 * invoke_tool dans _shared.py) - filtre defensivement tout element qui ne
 * ressemble pas a un edit valide plutot que de planter sur un rendu. */
export function parseEditFileEdits(args: Record<string, unknown>): EditFileEdit[] {
  if (!Array.isArray(args.edits)) return [];
  const edits: EditFileEdit[] = [];
  for (const item of args.edits as unknown[]) {
    if (
      item &&
      typeof item === "object" &&
      typeof (item as Record<string, unknown>).path === "string" &&
      typeof (item as Record<string, unknown>).old_string === "string" &&
      typeof (item as Record<string, unknown>).new_string === "string"
    ) {
      const e = item as Record<string, unknown>;
      edits.push({
        path: e.path as string,
        old_string: e.old_string as string,
        new_string: e.new_string as string,
      });
    }
  }
  return edits;
}

/** Resume compact d'un appel edit_file pour la ligne "target" (visible
 * sans deplier) - le JSON brut de `edits` (via formatArgs) serait illisible
 * une fois tronque a une ligne, surtout avec plusieurs hunks/fichiers. */
export function editFileTarget(args: Record<string, unknown>): string {
  const edits = parseEditFileEdits(args);
  if (edits.length === 0) return formatArgs(args);
  const paths = [...new Set(edits.map((e) => e.path))];
  if (paths.length === 1) {
    return `${paths[0]} (${edits.length} edit${edits.length > 1 ? "s" : ""})`;
  }
  return `${edits.length} edits across ${paths.length} files`;
}

// web_search prefixe son resultat d'un marqueur "[source: ...]" (voir
// tools/web.py) pour que l'app puisse afficher quelle API a repondu sans
// que l'utilisateur ait a deplier l'appel - jamais montre tel quel dans
// le detail du resultat, extrait puis retire par les deux fonctions
// ci-dessous (reutilisees pour les appels normaux et ceux d'une
// sous-tache multi-agent, voir multiAgentSubtaskDetail dans App.tsx).
const WEB_SEARCH_SOURCE_RE = /^\[source: (Tavily|DuckDuckGo)\]\n\n?/;

export function webSearchSource(result: string): string | undefined {
  return WEB_SEARCH_SOURCE_RE.exec(result)?.[1];
}

export function stripWebSearchSource(result: string): string {
  return result.replace(WEB_SEARCH_SOURCE_RE, "");
}

/** Shape commune a un vrai appel d'outil (ToolMsg) et a celui d'une
 * sous-tache multi-agent (MultiAgentSubtaskToolCall) - les deux seuls
 * appelants de toolResultDetail/toolDiffStats, qui n'utilisent rien de
 * plus specifique que ces trois champs. */
export interface ToolCallLike {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

/** Nombre de lignes ajoutees/retirees pour un appel d'ecriture - affiche
 * en permanence dans la ligne (+N/-N, voir ChatToolCallItem.additions/
 * deletions), donc visible sans avoir a deplier le detail complet du
 * resultat (qui reste, lui, derriere un clic - voir toolResultDetail dans
 * App.tsx). */
export function toolDiffStats(t: ToolCallLike): { additions?: number; deletions?: number } {
  const countLines = (s: string) => (s === "" ? 0 : s.split("\n").length);
  if (t.tool === "edit_file") {
    const edits = parseEditFileEdits(t.args);
    if (edits.length > 0) {
      return {
        additions: edits.reduce((sum, e) => sum + countLines(e.new_string), 0),
        deletions: edits.reduce((sum, e) => sum + countLines(e.old_string), 0),
      };
    }
  }
  if (t.tool === "write_file" && typeof t.args.content === "string") {
    return { additions: countLines(t.args.content) };
  }
  return {};
}
