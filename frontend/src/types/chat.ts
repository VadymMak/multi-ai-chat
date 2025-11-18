// File: src/types/chat.ts

/** Who produced the message bubble */
export type Sender =
  | "user"
  | "assistant" // ✅ some BE rows use this generic sender label
  | "openai"
  | "anthropic"
  | "grok"
  | "youtube"
  | "web"
  | "wikipedia"
  | "system" // system notices / dividers
  | "final"; // backend may label summary/divider as "final"

/** Downloadable file attached to a message */
/** Downloadable file attached to a message */
export type Attachment = {
  id: string | number; // ✅ Backend возвращает number
  /** filename shown to the user (e.g., "chat-output.pdf") */
  name: string;
  /** Original filename from upload */
  original_filename?: string; // ✅ ДОБАВЬ
  /** e.g., "image", "document", "data" */
  file_type?: "image" | "document" | "data"; // ✅ ДОБАВЬ
  /** e.g., "application/pdf" */
  mime: string;
  /** blob: or http(s):// */
  url: string;
  /** optional size in bytes */
  size?: number;
  /** Upload timestamp */
  uploaded_at?: string; // ✅ ДОБАВЬ
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
   * @deprecated Use `kind`. Kept for backward compatibility with older payloads.
   * Some servers may send "doc" to mean "markdown".
   */
  type?: "code" | "markdown" | "plain" | "poem_plain" | "poem_code" | "doc";
};

/** Supplementary sources (normalized) */
export type YouTubeSource = {
  title: string;
  url: string;
  description?: string;
  /** Optional canonicalized 11-char video id (used for thumbnails, etc.) */
  videoId?: string;
};
export type WebSource = {
  title: string;
  url: string;
  snippet?: string;
  /** Some backends send `description` instead of `snippet`; we accept both. */
  description?: string;
};
export type SourceBundle = {
  youtube?: YouTubeSource[];
  web?: WebSource[];
};

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
  sources?: SourceBundle;

  /** Legacy: still supported for backward compatibility */
  youtube?: YouTubeSource[];
  web?: WebSource[];

  /** Filtering / scoping context carried with the message */
  role_id?: number;
  project_id?: number | string;
  chat_session_id?: string;
}
