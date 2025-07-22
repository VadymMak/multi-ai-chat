export type Sender =
  | "user"
  | "openai"
  | "anthropic"
  | "grok"
  | "youtube"
  | "web"
  | "wikipedia"; // <- Add this

export interface ChatMessage {
  id: string;
  sender: Sender;
  text: string;
  isTyping?: boolean;
  isSummary?: boolean;
}
