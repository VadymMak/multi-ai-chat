// File: src/types/ai.ts
import type { ChatMessage, YouTubeSource, WebSource, RenderMeta } from "./chat";

/** Which model starts the AI-to-AI discussion on the backend */
export type AiStarter = "openai" | "anthropic";

/** Provider selector for /ask */
export type AskProvider = "openai" | "anthropic" | "all";

/** Normalized "sources" bundle used across responses.
 *  Allow optional description/snippet on elements for backend compatibility. */
export interface AskSources {
  youtube?: Array<YouTubeSource & { description?: string }>;
  web?: Array<WebSource & { description?: string }>;
}

/**
 * Response shape for /ask-ai-to-ai.
 * We normalize messages to ChatMessage[] for easy rendering,
 * and keep legacy top-level youtube/web arrays for compatibility.
 */
export interface AiToAiResponse {
  messages: ChatMessage[];
  youtube?: YouTubeSource[]; // description may also be present at runtime and is safely ignored
  web?: WebSource[]; // description may also be present at runtime and is safely ignored
  chat_session_id?: string;
}

/**
 * Minimal assistant message returned by /ask (before the UI maps it to ChatMessage).
 * For "all" provider, you'll see multiple of these (openai, anthropic, and a summary).
 */
export interface AskResponseMessage {
  /** "openai" | "anthropic" | "final" (kept loose for compatibility) */
  sender: string;
  text: string;
  isSummary?: boolean;

  /** Optional per-message sources (frontend also supports top-level `sources`) */
  sources?: AskSources;

  /** Optional render meta; `aiApi.ts` attaches this when present */
  render?: RenderMeta;
}

/** Full response for /ask */
export interface AskResponse {
  messages: AskResponseMessage[];
  chat_session_id: string;

  /** Optional top-level sources (backend may return either nested or top-level) */
  sources?: AskSources;
}
