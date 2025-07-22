// File: src/types/chat.ts

export type Sender =
  | "user"
  | "openai"
  | "anthropic"
  | "grok"
  | "youtube"
  | "web"
  | "wikipedia"
  | "system"; // ✅ For special system messages like dividers

// ✅ Extend this if needed in backend logic
export type ModelProvider = "openai" | "anthropic" | "grok" | "all"; // used only for routing, not as Sender

export interface ChatMessage {
  id: string;
  sender: Sender;
  text: string;
  isTyping?: boolean;
  isSummary?: boolean;

  // ✅ Used for filtering by memory context
  role_id?: number;
  project_id?: number | string;
  chat_session_id?: string;
}
