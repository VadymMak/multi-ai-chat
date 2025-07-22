export type Sender =
  | "user"
  | "openai"
  | "anthropic"
  | "grok"
  | "youtube"
  | "web"
  | "wikipedia"
  | "system"; // ✅ For special system messages like dividers

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
