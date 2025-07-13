export type Model = "grok" | "openai" | "anthropic" | "all";

export interface Message {
  text: string;
  sender: "user" | "ai";
  aiModel?: "grok" | "openai" | "anthropic" | "final";
  timestamp: string;
}

export interface YouTubeResult {
  title: string;
  videoId: string;
  url: string;
  description: string;
}
