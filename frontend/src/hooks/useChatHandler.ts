import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import type { Sender, ChatMessage } from "../types/chat";
import type { RenderKind } from "../types/chat";
import { renderSupplementary } from "../utils/renderSupplementary";

interface UseChatHandlerParams {
  input: string;
  setInput: (val: string) => void;
  abortRef: React.RefObject<AbortController | null>;
  provider: string | null;
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

/** Optional per-send overrides (used by quick buttons) */
type SendOverrides = {
  kind?: RenderKind;
  language?: string | null;
  filename?: string | null;
};

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
      if (!messageToSend || !roleId) return;

      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      const userMessage: ChatMessage = {
        id: `user-${uuidv4()}`,
        sender: "user",
        text: messageToSend,
      };
      addMessage(userMessage);
      setInput("");

      try {
        if (provider === "boost") {
          // ---- Boost path (Ai-to-Ai)
          const result = await sendAiToAiMessage(
            messageToSend,
            "openai",
            roleId,
            projectId,
            chatSessionId
          );

          for (const { sender, text, isSummary } of result.messages) {
            const id = `${sender}-${uuidv4()}`;
            addMessage({
              id,
              sender: sender as Sender,
              text: "",
              isTyping: true,
              isSummary,
            });
            await streamText(id, text || "⚠️ Empty", abortRef.current?.signal);
          }

          if (result.youtube) {
            await renderSupplementary(
              "youtube",
              result.youtube,
              addMessage,
              streamText,
              abortRef.current?.signal
            );
          }

          if (result.web) {
            await renderSupplementary(
              "web",
              result.web,
              addMessage,
              streamText,
              abortRef.current?.signal
            );
          }
        } else if (typedProvider) {
          // ---- Normal /ask path
          const askRes = await sendAiMessage(
            messageToSend,
            typedProvider,
            roleId,
            projectId,
            chatSessionId,
            overrides // <= pass quick-button overrides through
          );

          // Multi-model: stream each message
          if (typedProvider === "all") {
            for (const m of askRes.messages) {
              const id = `ai-${uuidv4()}`;
              const sender = (m.sender as Sender) || "openai";
              const text = String(m.text ?? "");
              const sources = (m as any).sources ?? (askRes as any).sources;
              const render = (m as any).render;

              addMessage({
                id,
                sender,
                text: "",
                isTyping: true,
                ...(render ? { render } : {}),
                ...(sources ? ({ sources } as any) : {}),
              });

              await streamText(
                id,
                text || "🤖 No response",
                abortRef.current?.signal
              );
            }
          } else {
            // Single provider: expect the first message as assistant response
            const m = askRes.messages?.[0] as any;
            const mappedSender: Sender = typedProvider;
            const id = `ai-${uuidv4()}`;
            const textOut = String(m?.text ?? "");
            const sources = m?.sources ?? (askRes as any)?.sources;
            const render = m?.render;

            addMessage({
              id,
              sender: mappedSender,
              text: "",
              isTyping: true,
              ...(render ? { render } : {}),
              ...(sources ? ({ sources } as any) : {}),
            });

            await streamText(
              id,
              textOut || "🤖 No response",
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
