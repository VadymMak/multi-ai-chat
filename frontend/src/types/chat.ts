export interface ChatMessage {
  id: string;
  sender: "user" | "openai" | "anthropic" | "grok";
  text: string;
  isTyping?: boolean;
  isSummary?: boolean; // ✅ Add this line
}

export interface ChatMessage {
  id: string;
  sender: "user" | "openai" | "anthropic" | "grok";
  text: string;
  isTyping?: boolean;
}
