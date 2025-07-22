// src/hooks/useStreamText.ts
import { useChatStore } from "../store/chatStore";

export const useStreamText = () => {
  return async (
    id: string,
    fullText: string,
    signal?: AbortSignal,
    baseDelay = 10
  ) => {
    const length = fullText.length;
    let step = 1;
    let delay = baseDelay;

    // Debug initial state
    console.debug(`[streamText] Begin: ID=${id}, length=${length}`);
    console.debug(`[streamText] Preview:`, fullText.slice(0, 100));

    // Adaptive streaming speed
    if (length > 600) {
      step = 4;
      delay = 4;
    } else if (length > 300) {
      step = 3;
      delay = 6;
    } else if (length > 150) {
      step = 2;
      delay = 8;
    }

    console.debug(`[streamText] Using step=${step}, delay=${delay}ms`);

    for (let i = 1; i <= length; i += step) {
      if (signal?.aborted) {
        console.warn(`[streamText] Aborted: ID=${id}`);
        return;
      }

      const chunk = fullText.slice(0, i);
      useChatStore.getState().updateMessageText(id, chunk);
      await new Promise((res) => setTimeout(res, delay));

      if (i % 50 === 0 || i + step >= length) {
        console.debug(`[streamText] Progress: ${i}/${length}`);
      }
    }

    // Final flush to ensure the entire message is shown
    if (fullText.length > 0) {
      useChatStore.getState().updateMessageText(id, fullText);
      console.debug(`[streamText] Final chunk flushed for ${id}`);
    }

    // Mark typing complete
    useChatStore.getState().markMessageDone(id);
    console.debug(`[streamText] Complete for ID=${id}`);
  };
};
