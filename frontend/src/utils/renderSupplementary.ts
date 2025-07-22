import { v4 as uuidv4 } from "uuid";
import type { ChatMessage, Sender } from "../types/chat";

/**
 * Renders supplementary data like YouTube or Web results into the chat.
 *
 * @param type - Either "youtube" or "web"
 * @param data - The supplementary data (should be an array of results)
 * @param addMessage - Function to add the message to the chat store
 * @param streamText - Function to stream the text character-by-character
 * @param abortSignal - Optional AbortSignal for cancellation support
 * @param role_id - Optional role ID for context scoping
 * @param project_id - Optional project ID for context scoping
 * @param chat_session_id - Optional chat session ID for scoping
 */
export async function renderSupplementary(
  type: "youtube" | "web",
  data: any,
  addMessage: (msg: ChatMessage) => void,
  streamText: (id: string, text: string, signal?: AbortSignal) => Promise<void>,
  abortSignal?: AbortSignal,
  role_id?: number,
  project_id?: number | string,
  chat_session_id?: string
) {
  const id = `${type}-${uuidv4()}`;
  const sender = type as Sender;

  const text = Array.isArray(data)
    ? data
        .map((v) =>
          type === "youtube"
            ? `▶️ [${v.title}](${v.url})`
            : `🌐 [${v.title}](${v.url})\n${v.snippet || ""}`
        )
        .join("\n\n")
    : `⚠️ Invalid ${type} results format.`;

  addMessage({
    id,
    sender,
    text: "",
    isTyping: true,
    role_id,
    project_id,
    chat_session_id,
  });

  await streamText(id, text, abortSignal);
}
