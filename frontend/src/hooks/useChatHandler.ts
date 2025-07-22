// File: src/hooks/useChatHandler.ts
import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import type { Sender, ChatMessage } from "../types/chat";
import type { RenderKind } from "../types/chat";
import { renderSupplementary } from "../utils/renderSupplementary";
import { useChatStore } from "../store/chatStore";

interface UseChatHandlerParams {
  input: string;
  setInput: (val: string) => void;
  abortRef: React.RefObject<AbortController | null>;
  provider: string | null; // "boost" or null
  typedProvider: "openai" | "anthropic" | "all" | null;
  roleId: number | null;
  projectId: string | number;
  chatSessionId?: string;
  setTyping: (val: boolean) => void;
  addMessage: (msg: ChatMessage) => void;
  streamText: (id: string, text: string, signal?: AbortSignal) => Promise<void>;
  sendAiMessage: typeof import("../services/aiApi").sendAiMessage;
  sendAiToAiMessage: typeof import("../services/aiApi").sendAiToAiMessage;
}

/** Optional per-send overrides */
type SendOverrides = {
  /** legacy from UI buttons; we'll map to output_mode/presentation */
  kind?: RenderKind;
  /** new explicit fields the backend understands */
  output_mode?: "plain" | "doc" | "code";
  presentation?: "default" | "poem_plain" | "poem_code";
  language?: string | null;
  filename?: string | null;
};

function deriveMode(
  over?: SendOverrides
): {
  output_mode?: "plain" | "doc" | "code";
  presentation?: "default" | "poem_plain" | "poem_code";
} {
  if (over?.output_mode || over?.presentation) {
    return {
      output_mode: over.output_mode,
      presentation: over.presentation ?? "default",
    };
  }
  switch (over?.kind) {
    case "plain":
      return { output_mode: "plain", presentation: "default" };
    case "markdown":
      return { output_mode: "doc", presentation: "default" };
    case "code":
      return { output_mode: "code", presentation: "default" };
    case "poem_plain":
      return { output_mode: "plain", presentation: "poem_plain" };
    case "poem_code":
      return { output_mode: "code", presentation: "poem_code" };
    default:
      return { output_mode: "doc", presentation: "default" };
  }
}

export const useChatHandler = ({
  input,
  setInput,
  abortRef,
  provider,
  typedProvider,
  roleId,
  projectId,
  chatSessionId,
  setTyping,
  addMessage,
  streamText,
  sendAiMessage,
  sendAiToAiMessage,
}: UseChatHandlerParams) => {
  const handleSend = useCallback(
    async (text?: string, overrides?: SendOverrides) => {
      const messageToSend = (text ?? input).trim();
      if (!messageToSend) return;
      if (!roleId || roleId <= 0) return;
      if (
        projectId === null ||
        projectId === undefined ||
        String(projectId).trim() === ""
      )
        return;

      // Prepare abort controller for this turn
      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      // Snapshot the best-known session id (may update after server response)
      const initialSessionId =
        chatSessionId || useChatStore.getState().chatSessionId || "";

      // Echo user message immediately (tagged so ChatArea filter keeps it)
      const userMessage: ChatMessage = {
        id: `user-${uuidv4()}`,
        sender: "user",
        text: messageToSend,
        chat_session_id: initialSessionId,
        role_id: roleId,
        project_id: String(projectId),
      };
      addMessage(userMessage);
      setInput("");

      try {
        if (provider === "boost") {
          // ===== Boost path (Ai-to-Ai) =====
          const result = await sendAiToAiMessage(
            messageToSend,
            "openai",
            roleId,
            projectId,
            initialSessionId
          );

          // In case backend rotated/created a new session, adopt it
          if ((result as any)?.chat_session_id) {
            useChatStore
              .getState()
              .handleSessionIdUpdateFromAsk(
                String((result as any).chat_session_id)
              );
          }
          const sessId =
            useChatStore.getState().chatSessionId || initialSessionId;

          for (const { sender, text, isSummary } of result.messages ?? []) {
            const id = `${sender}-${uuidv4()}`;
            addMessage({
              id,
              sender: (sender as Sender) ?? "anthropic",
              text: "",
              isTyping: true,
              isSummary,
              chat_session_id: sessId,
              role_id: roleId,
              project_id: String(projectId),
            });
            await streamText(id, text || "⚠️ Empty", abortRef.current?.signal);
          }

          if (result.youtube?.length) {
            await renderSupplementary(
              "youtube",
              result.youtube,
              (m) =>
                addMessage({
                  ...m,
                  chat_session_id: sessId,
                  role_id: roleId,
                  project_id: String(projectId),
                } as ChatMessage),
              (id, t, sig) => streamText(id, t, sig),
              abortRef.current?.signal
            );
          }
          if (result.web?.length) {
            await renderSupplementary(
              "web",
              result.web,
              (m) =>
                addMessage({
                  ...m,
                  chat_session_id: sessId,
                  role_id: roleId,
                  project_id: String(projectId),
                } as ChatMessage),
              (id, t, sig) => streamText(id, t, sig),
              abortRef.current?.signal
            );
          }
          return;
        }

        if (typedProvider) {
          // ===== Normal /api/ask path =====
          const mode = deriveMode(overrides);

          const askRes = await sendAiMessage(
            messageToSend,
            typedProvider,
            roleId,
            projectId,
            initialSessionId,
            {
              ...overrides,
              ...mode,
            }
          );

          // Adopt server-provided session id if present
          if ((askRes as any)?.chat_session_id) {
            useChatStore
              .getState()
              .handleSessionIdUpdateFromAsk(
                String((askRes as any).chat_session_id)
              );
          }
          const sessId =
            useChatStore.getState().chatSessionId || initialSessionId;

          // Multi-model
          if (typedProvider === "all") {
            for (const m of askRes.messages ?? []) {
              const id = `ai-${uuidv4()}`;
              const sender = (m.sender as Sender) || "openai";
              const textOut = String(m.text ?? "");
              const sources = (m as any).sources ?? (askRes as any).sources;
              const render = (m as any).render;

              addMessage({
                id,
                sender,
                text: "",
                isTyping: true,
                ...(render ? { render } : {}),
                ...(sources ? ({ sources } as any) : {}),
                chat_session_id: sessId,
                role_id: roleId,
                project_id: String(projectId),
              });

              await streamText(
                id,
                textOut || "🤖 No response",
                abortRef.current?.signal
              );
            }

            // supplemental
            if ((askRes as any)?.youtube?.length) {
              await renderSupplementary(
                "youtube",
                (askRes as any).youtube,
                (m) =>
                  addMessage({
                    ...m,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id, t, sig) => streamText(id, t, sig),
                abortRef.current?.signal
              );
            }
            if ((askRes as any)?.web?.length) {
              await renderSupplementary(
                "web",
                (askRes as any).web,
                (m) =>
                  addMessage({
                    ...m,
                    chat_session_id: sessId,
                    role_id: roleId,
                    project_id: String(projectId),
                  } as ChatMessage),
                (id, t, sig) => streamText(id, t, sig),
                abortRef.current?.signal
              );
            }

            return;
          }

          // Single provider
          const m = askRes.messages?.[0] as any;
          const id = `ai-${uuidv4()}`;
          const textOut = String(m?.text ?? "");
          const sources = m?.sources ?? (askRes as any)?.sources;
          const render = m?.render;

          addMessage({
            id,
            sender: typedProvider,
            text: "",
            isTyping: true,
            ...(render ? { render } : {}),
            ...(sources ? ({ sources } as any) : {}),
            chat_session_id: sessId,
            role_id: roleId,
            project_id: String(projectId),
          });

          await streamText(
            id,
            textOut || "🤖 No response",
            abortRef.current?.signal
          );

          // supplemental
          if ((askRes as any)?.youtube?.length) {
            await renderSupplementary(
              "youtube",
              (askRes as any).youtube,
              (m2) =>
                addMessage({
                  ...m2,
                  chat_session_id: sessId,
                  role_id: roleId,
                  project_id: String(projectId),
                } as ChatMessage),
              (id2, t2, sig2) => streamText(id2, t2, sig2),
              abortRef.current?.signal
            );
          }
          if ((askRes as any)?.web?.length) {
            await renderSupplementary(
              "web",
              (askRes as any).web,
              (m2) =>
                addMessage({
                  ...m2,
                  chat_session_id: sessId,
                  role_id: roleId,
                  project_id: String(projectId),
                } as ChatMessage),
              (id2, t2, sig2) => streamText(id2, t2, sig2),
              abortRef.current?.signal
            );
          }
        }
      } catch (err) {
        console.error("❌ send failed:", err);
      } finally {
        setTyping(false);
      }
    },
    [
      input,
      provider,
      typedProvider,
      roleId,
      projectId,
      chatSessionId,
      setTyping,
      addMessage,
      streamText,
      sendAiMessage,
      sendAiToAiMessage,
      setInput,
      abortRef,
    ]
  );

  return { handleSend };
};
