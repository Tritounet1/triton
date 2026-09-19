import { describe, expect, it } from "vitest";
import {
  assistantGroupModel,
  editFileTarget,
  extractUserContent,
  formatSessionLabel,
  groupMessages,
  historyToMessages,
  isPdfDataUrl,
  parseEditFileEdits,
  parseToolDisplay,
  stripWebSearchSource,
  toBlocks,
  toolCallStatus,
  toolDiffStats,
  truncateBeforeTurn,
  userMessageAtTurn,
  webSearchSource,
  type ChatMsg,
  type RawSessionMessage,
} from "./chatMessages";

describe("extractUserContent", () => {
  it("wraps a plain string with empty images/files", () => {
    expect(extractUserContent("hello")).toEqual({ text: "hello", images: [], files: [] });
  });

  it("splits a content-part list into text/images/files", () => {
    const result = extractUserContent([
      { type: "text", text: "look at this" },
      { type: "image_url", image_url: { url: "data:image/png;base64,abc" } },
      { type: "file", file: { filename: "doc.pdf", file_data: "data:application/pdf;base64,xyz" } },
    ]);
    expect(result).toEqual({
      text: "look at this",
      images: ["data:image/png;base64,abc"],
      files: [{ name: "doc.pdf", dataUrl: "data:application/pdf;base64,xyz" }],
    });
  });

  it("joins multiple text parts with a newline", () => {
    expect(
      extractUserContent([
        { type: "text", text: "line one" },
        { type: "text", text: "line two" },
      ]).text,
    ).toBe("line one\nline two");
  });
});

describe("isPdfDataUrl", () => {
  it("recognizes a PDF data url", () => {
    expect(isPdfDataUrl("data:application/pdf;base64,abc")).toBe(true);
  });

  it("rejects a non-PDF data url", () => {
    expect(isPdfDataUrl("data:image/png;base64,abc")).toBe(false);
  });
});

function userMsg(text: string): Extract<ChatMsg, { kind: "user" }> {
  return { kind: "user", text, time: 0 };
}

describe("truncateBeforeTurn", () => {
  it("cuts the list right before the nth user message", () => {
    const msgs: ChatMsg[] = [
      userMsg("1"),
      { kind: "assistant", text: "reply 1", time: 0 },
      userMsg("2"),
      { kind: "assistant", text: "reply 2", time: 0 },
    ];
    expect(truncateBeforeTurn(msgs, 2)).toEqual(msgs.slice(0, 2));
  });

  it("is a no-op when turnIndex is out of bounds", () => {
    const msgs: ChatMsg[] = [userMsg("1")];
    expect(truncateBeforeTurn(msgs, 5)).toBe(msgs);
  });
});

describe("userMessageAtTurn", () => {
  it("finds the nth user message (1-based)", () => {
    const second = userMsg("2");
    const msgs: ChatMsg[] = [userMsg("1"), second];
    expect(userMessageAtTurn(msgs, 2)).toBe(second);
  });

  it("returns undefined when there is no such turn", () => {
    expect(userMessageAtTurn([userMsg("1")], 3)).toBeUndefined();
  });
});

describe("formatSessionLabel", () => {
  it("formats a session id into a readable date/time", () => {
    expect(formatSessionLabel("2026-08-28_101500")).toBe("28/08/2026 10:15");
  });

  it("returns the id unchanged when it doesn't match the expected shape", () => {
    expect(formatSessionLabel("not-a-session-id")).toBe("not-a-session-id");
  });
});

describe("historyToMessages", () => {
  it("turns a user message into a ChatMsg", () => {
    const raw: RawSessionMessage[] = [{ role: "user", content: "hi" }];
    const out = historyToMessages(raw);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ kind: "user", text: "hi" });
  });

  it("pairs an assistant tool_call with its tool result", () => {
    const raw: RawSessionMessage[] = [
      {
        role: "assistant",
        content: null,
        model: "z-ai/glm-5.3-flash",
        tool_calls: [
          { id: "call_1", function: { name: "read_file", arguments: '{"path":"a.txt"}' } },
        ],
      },
      { role: "tool", content: "file contents", tool_call_id: "call_1" },
    ];
    const out = historyToMessages(raw);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      kind: "tool",
      tool: "read_file",
      args: { path: "a.txt" },
      result: "file contents",
      model: "z-ai/glm-5.3-flash",
    });
  });

  it("emits both tool calls and trailing assistant text from the same message", () => {
    const raw: RawSessionMessage[] = [
      {
        role: "assistant",
        content: "done",
        model: "gpt-5",
        tool_calls: [{ id: "call_1", function: { name: "run_shell", arguments: "{}" } }],
      },
      { role: "tool", content: "ok", tool_call_id: "call_1" },
    ];
    const out = historyToMessages(raw);
    expect(out.map((m) => m.kind)).toEqual(["tool", "assistant"]);
    expect(out[1]).toMatchObject({ kind: "assistant", text: "done", model: "gpt-5" });
  });

  it("keeps generated images with the producing model", () => {
    const out = historyToMessages([
      {
        role: "assistant",
        content: "",
        model: "openai/gpt-image-1",
        generated_images: ["data:image/png;base64,abc"],
      },
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      kind: "assistant",
      text: "",
      images: ["data:image/png;base64,abc"],
      model: "openai/gpt-image-1",
    });
    expect(typeof out[0]?.time).toBe("number");
  });
});

describe("groupMessages / toBlocks", () => {
  it("groups consecutive assistant/tool messages under one entry", () => {
    const msgs: ChatMsg[] = [
      userMsg("q"),
      { kind: "tool", tool: "read_file", args: {}, result: "ok", time: 0 },
      { kind: "assistant", text: "answer", time: 0 },
    ];
    const groups = groupMessages(msgs);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ type: "user", turnIndex: 1 });
    expect(groups[1]?.type).toBe("assistant");
    if (groups[1]?.type === "assistant") {
      expect(groups[1].items).toHaveLength(2);
      expect(groups[1].precedingTurnIndex).toBe(1);
    }
  });

  it("keeps a later model available when an earlier tool-step message lacks it", () => {
    const groups = groupMessages([
      userMsg("supprime le fichier"),
      { kind: "assistant", text: "Je le trouve.", time: 0 },
      { kind: "tool", tool: "delete_file", args: {}, result: "ok", time: 0 },
      { kind: "assistant", text: "Supprimé.", time: 0, model: "z-ai/glm-5.3-flash" },
    ]);
    const group = groups[1];
    expect(group?.type).toBe("assistant");
    if (group?.type === "assistant") {
      expect(assistantGroupModel(group.items)).toBe("z-ai/glm-5.3-flash");
    }
  });

  it("does not split an assistant response around an informational save notice", () => {
    const groups = groupMessages([
      userMsg("supprime le fichier"),
      { kind: "assistant", text: "Je le trouve.", time: 0 },
      { kind: "tool", tool: "delete_file", args: {}, result: "ok", time: 0 },
      { kind: "info", text: "Point de restauration créé.", time: 0 },
      { kind: "assistant", text: "Supprimé.", time: 0, model: "z-ai/glm-5.3-flash" },
    ]);
    expect(groups.map((group) => group.type)).toEqual(["user", "assistant", "system"]);
    const assistant = groups[1];
    expect(assistant?.type).toBe("assistant");
    if (assistant?.type === "assistant") {
      expect(assistant.items).toHaveLength(3);
      expect(assistantGroupModel(assistant.items)).toBe("z-ai/glm-5.3-flash");
    }
  });

  it("does not lose a tool call between two other tool calls when converted to blocks", () => {
    // regression check for the "loader disappearing between two tool
    // calls" bug this session: two consecutive tool calls must merge into
    // a single "tools" block, not silently drop the middle one.
    const items: (Extract<ChatMsg, { kind: "assistant" | "tool" }>)[] = [
      { kind: "tool", tool: "read_file", args: {}, result: "a", time: 0 },
      { kind: "tool", tool: "write_file", args: {}, result: "b", time: 0 },
      { kind: "assistant", text: "done", time: 0 },
    ];
    const blocks = toBlocks(items);
    expect(blocks).toHaveLength(2);
    expect(blocks[0]).toMatchObject({ kind: "tools" });
    if (blocks[0]?.kind === "tools") {
      expect(blocks[0].items.map((t) => t.tool)).toEqual(["read_file", "write_file"]);
    }
    expect(blocks[1]).toMatchObject({ kind: "text" });
  });
});

describe("parseToolDisplay", () => {
  it("splits an mcp-prefixed tool name into label + server", () => {
    expect(parseToolDisplay("mcp__github__create_issue")).toEqual({
      label: "create_issue",
      server: "github",
    });
  });

  it("returns no server for a native tool", () => {
    expect(parseToolDisplay("write_file")).toEqual({ label: "write_file", server: null });
  });
});

describe("toolCallStatus", () => {
  it("flags a result starting with 'error' as an error", () => {
    expect(toolCallStatus("error: file not found")).toBe("error");
  });

  it("flags a denied action as an error", () => {
    expect(toolCallStatus("action denied by user")).toBe("error");
  });

  it("treats anything else as complete", () => {
    expect(toolCallStatus("file written successfully")).toBe("complete");
  });
});

describe("parseEditFileEdits", () => {
  it("parses a well-formed edits array", () => {
    const edits = parseEditFileEdits({
      edits: [{ path: "a.ts", old_string: "old", new_string: "new" }],
    });
    expect(edits).toEqual([{ path: "a.ts", old_string: "old", new_string: "new" }]);
  });

  it("silently drops malformed entries instead of throwing", () => {
    const edits = parseEditFileEdits({ edits: [{ path: "a.ts" }, "not an object", null] });
    expect(edits).toEqual([]);
  });

  it("returns an empty array when edits is missing", () => {
    expect(parseEditFileEdits({})).toEqual([]);
  });
});

describe("editFileTarget", () => {
  it("shows a single path with its edit count", () => {
    const args = { edits: [{ path: "a.ts", old_string: "x", new_string: "y" }] };
    expect(editFileTarget(args)).toBe("a.ts (1 edit)");
  });

  it("pluralizes edit count for multiple hunks on one file", () => {
    const args = {
      edits: [
        { path: "a.ts", old_string: "x", new_string: "y" },
        { path: "a.ts", old_string: "p", new_string: "q" },
      ],
    };
    expect(editFileTarget(args)).toBe("a.ts (2 edits)");
  });

  it("summarizes across multiple files", () => {
    const args = {
      edits: [
        { path: "a.ts", old_string: "x", new_string: "y" },
        { path: "b.ts", old_string: "p", new_string: "q" },
      ],
    };
    expect(editFileTarget(args)).toBe("2 edits across 2 files");
  });

  it("falls back to formatArgs when there are no valid edits", () => {
    expect(editFileTarget({ foo: "bar" })).toContain("foo");
  });
});

describe("webSearchSource / stripWebSearchSource", () => {
  it("extracts the source marker", () => {
    expect(webSearchSource("[source: Tavily]\n\nresult text")).toBe("Tavily");
  });

  it("returns undefined when there is no marker", () => {
    expect(webSearchSource("plain result")).toBeUndefined();
  });

  it("strips the marker from the result", () => {
    expect(stripWebSearchSource("[source: DuckDuckGo]\n\nresult text")).toBe("result text");
  });

  it("leaves unmarked results untouched", () => {
    expect(stripWebSearchSource("plain result")).toBe("plain result");
  });
});

describe("toolDiffStats", () => {
  it("counts additions/deletions for an edit_file call", () => {
    const stats = toolDiffStats({
      tool: "edit_file",
      args: { edits: [{ path: "a.ts", old_string: "a\nb", new_string: "c\nd\ne" }] },
      result: "ok",
    });
    expect(stats).toEqual({ additions: 3, deletions: 2 });
  });

  it("counts additions only for a write_file call", () => {
    const stats = toolDiffStats({
      tool: "write_file",
      args: { content: "line1\nline2" },
      result: "ok",
    });
    expect(stats).toEqual({ additions: 2 });
  });

  it("returns nothing for a non-writing tool", () => {
    expect(toolDiffStats({ tool: "read_file", args: {}, result: "ok" })).toEqual({});
  });
});
