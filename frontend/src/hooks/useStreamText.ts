// src/hooks/useStreamText.ts
import { useChatStore } from "../store/chatStore";

export const useStreamText = () => {
  return async (
    id: string,
    fullText: string,
    signal?: AbortSignal,
    delay = 3
  ) => {
    console.log(
      `[streamText] Starting stream for ${id}:`,
      fullText.slice(0, 60)
    );

    for (let i = 1; i <= fullText.length; i++) {
      if (signal?.aborted) {
        console.log(`[streamText] Aborted for ${id}`);
        return;
      }
      await new Promise((res) => setTimeout(res, delay));
      useChatStore.getState().updateMessageText(id, fullText.slice(0, i));
    }

    console.log(`[streamText] Done streaming for ${id}`);
    useChatStore.getState().markMessageDone(id);
  };
};
