// src/hooks/useChatHandler.ts

import { useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import type { Sender, ChatMessage } from "../types/chat";
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
    async (text?: string) => {
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
          const result = await sendAiMessage(
            messageToSend,
            typedProvider,
            roleId,
            projectId
          );

          const mappedSender: Sender =
            typedProvider === "all" ? "openai" : typedProvider;
          const id = `ai-${uuidv4()}`;

          addMessage({ id, sender: mappedSender, text: "", isTyping: true });
          await streamText(
            id,
            result.messages[1]?.text || "🤖 No response",
            abortRef.current?.signal
          );
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
