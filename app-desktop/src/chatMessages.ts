// Pure types/functions turning a session's raw history (RawSessionMessage[],
// as returned by the server) into render-ready chat messages (ChatMsg[]) -
// extracted from App.tsx so this file only exports non-components (see
// react-refresh/only-export-components) and so they can be unit-tested
// without mounting all of App.tsx (see chatMessages.test.ts).
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
  | { kind: "assistant"; text: string; time: number; model?: string; images?: string[] }
  | {
      kind: "tool";
      // only present for a live multi-agent subtask (see dispatchMultiAgent):
      // lets us update the same entry instead of stacking a new one per poll.
      id?: string;
      tool: string;
      args: Record<string, unknown>;
      result: string;
      time: number;
      // model that requested this tool call; useful when a turn ends before
      // producing a final text response.
      model?: string;
      // explicit status for a live multi-agent subtask (known without having
      // to infer it from text, unlike an already-finished real tool call -
      // see toolCallStatus).
      status?: "pending" | "running" | "complete" | "error";
      // only present for a multi-agent subtask: its description (its own
      // line's "target") and the tools it has already called, updated live
      // while it runs (see pollMultiAgentRun / multiAgentSubtaskDetail).
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
  generated_images?: string[];
}

/** A stored user message can be either a plain string or a list of parts
 * (text + images/files) as soon as an attachment was sent (see
 * build_user_content server-side). */
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

/** Same convention as server.py's truncate_before_turn: cuts `msgs` right
 * before the user message that starts `turnIndex` (1-based), so the local
 * display immediately reflects what edit_turn_index will do server-side (no
 * waiting on the next SSE event to see old turns disappear). turnIndex not
 * found (out of bounds): no-op, returns msgs as-is. */
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

/** The user message that starts `turnIndex` (1-based) - used by "regenerate"
 * to find the text/attachments of the turn to resend as-is. */
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

/** session id in the 2026-08-28_101500 format -> "28/08/2026 10:15" */
export function formatSessionLabel(id: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})(?:-[a-f0-9]{10})?$/.exec(id);
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
          // a "tool" message's content (a tool call's result) is always a
          // plain string - only a "user" message can hold a list of parts
          // (text + images, see extractUserContent), hence the guard even
          // though the shared type is wider.
          result: typeof toolResult?.content === "string" ? toolResult.content : "",
          time: now,
          model: m.model,
        });
      }
      if ((typeof m.content === "string" && m.content) || m.generated_images?.length) {
        out.push({
          kind: "assistant",
          text: typeof m.content === "string" ? m.content : "",
          time: now,
          model: m.model,
          images: m.generated_images?.length ? m.generated_images : undefined,
        });
      }
    }
  }

  return out;
}

export type AssistantMsg = Extract<ChatMsg, { kind: "assistant" }>;
export type ToolMsg = Extract<ChatMsg, { kind: "tool" }>;

export type RenderGroup =
  // turnIndex: the same "1-based nth user message" as server-side
  // turn_index_of (see server.py) - what edit_turn_index expects, so it's
  // computed once here rather than recounted on every "edit" click.
  | { type: "user"; msg: Extract<ChatMsg, { kind: "user" }>; turnIndex: number }
  | { type: "system"; msg: Extract<ChatMsg, { kind: "info" | "error" }> }
  // precedingTurnIndex: the user turn that produced this group - what
  // "regenerate" sends back as edit_turn_index to re-request the exact same
  // response.
  | { type: "assistant"; items: (AssistantMsg | ToolMsg)[]; precedingTurnIndex: number };

/** Groups consecutive assistant/tool messages under a single avatar (like a
 * real thread), instead of a repeated avatar per response fragment. */
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
        // An info message can arrive between two steps of the same turn
        // (e.g. the restore point created right before a write). It must
        // not bring back a second avatar for the same response; keep it
        // visually after the group but attach what follows to the
        // previous assistant.
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

/** The most recent known model for a grouped response. Older histories could
 * omit the model on intermediate fragments around a tool call, even though
 * the final response does have it. */
export function assistantGroupModel(items: (AssistantMsg | ToolMsg)[]): string | undefined {
  return [...items].reverse().find((item) => Boolean(item.model))?.model;
}

export type Block =
  { kind: "tools"; items: ToolMsg[] } | { kind: "text"; msg: AssistantMsg };

/** Within an assistant group, merges consecutive tool calls into a single
 * ChatToolCalls (natively collapsible when several), separates out text. */
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
 * "server-name" } (see mcp_client.py's tool_key/MCP_PREFIX server-side); a
 * native tool (write_file, run_shell...) has no such prefix -> no server.
 * Used for the "Claude wants to use X from Y" permission-prompt style. */
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

/** edit_file now accepts several hunks/files in a single call (see
 * filesystem.py): its arguments are `{edits: [{path, old_string,
 * new_string, replace_all?}, ...]}` rather than flat old_string/new_string.
 * The model isn't forced to follow the schema (see invoke_tool in
 * _shared.py) - defensively filters out anything that doesn't look like a
 * valid edit rather than crashing on render. */
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

/** Compact summary of an edit_file call for the "target" line (visible
 * without expanding) - `edits`'s raw JSON (via formatArgs) would be
 * unreadable once truncated to one line, especially with several
 * hunks/files. */
export function editFileTarget(args: Record<string, unknown>): string {
  const edits = parseEditFileEdits(args);
  if (edits.length === 0) return formatArgs(args);
  const paths = [...new Set(edits.map((e) => e.path))];
  if (paths.length === 1) {
    return `${paths[0]} (${edits.length} edit${edits.length > 1 ? "s" : ""})`;
  }
  return `${edits.length} edits across ${paths.length} files`;
}

// web_search prefixes its result with a "[source: ...]" marker (see
// tools/web.py) so the app can show which API answered without the user
// expanding the call - never shown as-is in the result detail, extracted
// then stripped by the two functions below (reused for regular calls and
// multi-agent subtask ones, see multiAgentSubtaskDetail in App.tsx).
const WEB_SEARCH_SOURCE_RE = /^\[source: (Tavily|DuckDuckGo)\]\n\n?/;

export function webSearchSource(result: string): string | undefined {
  return WEB_SEARCH_SOURCE_RE.exec(result)?.[1];
}

export function stripWebSearchSource(result: string): string {
  return result.replace(WEB_SEARCH_SOURCE_RE, "");
}

/** Shape shared by a real tool call (ToolMsg) and a multi-agent subtask one
 * (MultiAgentSubtaskToolCall) - the only two callers of
 * toolResultDetail/toolDiffStats, which use nothing more specific than
 * these three fields. */
export interface ToolCallLike {
  tool: string;
  args: Record<string, unknown>;
  result: string;
}

/** Lines added/removed for a write call - shown permanently in the line
 * (+N/-N, see ChatToolCallItem.additions/deletions), so visible without
 * expanding the full result detail (which stays behind a click - see
 * toolResultDetail in App.tsx). */
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
