// File: src/types/chat.ts

/** Who produced the message bubble */
export type Sender =
  | "user"
  | "openai"
  | "anthropic"
  | "grok"
  | "youtube"
  | "web"
  | "wikipedia"
  | "system" // system notices / dividers
  | "final"; // backend may label summary/divider as "final"

/** Downloadable file attached to a message */
export type Attachment = {
  id: string;
  name: string; // filename shown to the user (e.g., "chat-output.pdf")
  mime: string; // e.g., "application/pdf"
  url: string; // blob: or http(s)://
  size?: number; // optional bytes
};

/** Output-mode / presentation kind coming from backend or UI */
export type RenderKind =
  | "markdown"
  | "plain"
  | "code"
  | "poem_plain"
  | "poem_code";

/** Optional render metadata from backend (unified) */
export type RenderMeta = {
  /** Unified kind the UI should follow */
  kind: RenderKind;

  /** Optional language hint for code blocks (e.g., "typescript") */
  language?: string | null;

  /** Optional filename hint (e.g., "index.ts") */
  filename?: string | null;

  /**
   * @deprecated use `kind`. Kept for backward compatibility with older payloads.
   * Some servers may send "doc" to mean "markdown".
   */
  type?: "code" | "markdown" | "plain" | "poem_plain" | "poem_code" | "doc";
};

/** Supplementary sources (normalized) */
export type YouTubeSource = { title: string; url: string };
export type WebSource = { title: string; url: string; snippet?: string };

/** Unified message shape used across the app */
export interface ChatMessage {
  id: string;
  sender: Sender;
  text: string;

  /** UI state flags */
  isTyping?: boolean;
  isSummary?: boolean;

  /** Optional timestamp (ISO string) if you store it */
  timestamp?: string;

  /** Downloadable attachments (e.g., generated PDF) */
  attachments?: Attachment[];

  /** Optional render meta (when the backend asks for specific formatting) */
  render?: RenderMeta;

  /** Preferred: normalized supplementary sources */
  sources?: {
    youtube?: YouTubeSource[];
    web?: WebSource[];
  };

  /** Legacy: still supported for backward compatibility */
  youtube?: YouTubeSource[];
  web?: WebSource[];

  /** Filtering / scoping context */
  role_id?: number;
  project_id?: number | string;
  chat_session_id?: string;
}
