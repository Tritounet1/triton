import { API_BASE } from "./api";

export interface ChatRequest {
  session_id: string | null;
  message: string;
  project_id: string | null;
  attachments: { name: string; data_url: string }[];
  edit_turn_index: number | null;
  model: string | null;
}

/** Owns the HTTP boundary of a streaming chat request; event handling stays separate. */
export function startChatStream(request: ChatRequest, signal: AbortSignal): Promise<Response> {
  return fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
}
