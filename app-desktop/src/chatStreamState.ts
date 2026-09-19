import type { ChatMsg } from "./chatMessages";

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function interruptedAssistantText(text: string): string {
  return text ? `${text}\n\n*(interrompu)*` : "*(interrompu)*";
}

export function upsertAssistantMessage(
  messages: ChatMsg[],
  text: string,
  model?: string,
): ChatMsg[] {
  const last = messages[messages.length - 1];
  if (last?.kind === "assistant") {
    return [...messages.slice(0, -1), { ...last, text, ...(model ? { model } : {}) }];
  }
  return [...messages, { kind: "assistant", text, time: Date.now(), ...(model ? { model } : {}) }];
}
