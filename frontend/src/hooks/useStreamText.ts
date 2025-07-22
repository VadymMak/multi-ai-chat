// File: src/hooks/useStreamText.ts
// Stream text into a message with RAF batching + abort safety
// API unchanged: useStreamText()(id, fullText, signal?, baseDelay?)
import { useChatStore } from "../store/chatStore";
import { STREAM_BATCH_MS } from "../constants"; // make sure this exists (see note below)

const FLUSH_FALLBACK_MS = (STREAM_BATCH_MS as number) ?? 32;

export const useStreamText = () => {
  return async (
    id: string,
    fullText: string,
    signal?: AbortSignal,
    baseDelay = 10
  ): Promise<void> => {
    const { updateMessageText, markMessageDone } = useChatStore.getState();

    const length = fullText.length;
    if (length === 0) {
      updateMessageText(id, "");
      markMessageDone(id); // flip message.isTyping -> false
      return;
    }

    // Adaptive speed (keeps previous behavior)
    let step = 1;
    let delay = baseDelay;
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

    let i = 0;
    let aborted = false;

    let rafId: number | null = null;
    let fallbackId: number | null = null;
    let timerId: number | null = null;

    const debug =
      process.env.NODE_ENV !== "production"
        ? (msg: string) => console.debug?.(`[streamText] ${msg} :: id=${id}`)
        : () => {};

    debug(`Begin: length=${length}, step=${step}, delay=${delay}ms`);

    const doFlush = () => {
      rafId = null;
      const slice = fullText.slice(0, i);
      useChatStore.getState().updateMessageText(id, slice);
    };

    const scheduleFlush = () => {
      if (typeof requestAnimationFrame === "function" && rafId == null) {
        rafId = requestAnimationFrame(doFlush);
      } else {
        // environments without RAF
        doFlush();
      }
      if (fallbackId == null) {
        fallbackId = window.setTimeout(() => {
          fallbackId = null;
          doFlush();
        }, FLUSH_FALLBACK_MS);
      }
    };

    const clearSchedulers = () => {
      if (rafId != null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(rafId);
      }
      if (fallbackId != null) clearTimeout(fallbackId);
      if (timerId != null) clearTimeout(timerId);
      rafId = null;
      fallbackId = null;
      timerId = null;
    };

    const finalize = () => {
      clearSchedulers();
      useChatStore.getState().updateMessageText(id, fullText); // final flush
      useChatStore.getState().markMessageDone(id); // stop per-message typing
      debug("Complete (final flush)");
    };

    const onAbort = () => {
      aborted = true;
      clearSchedulers();
      // flush whatever we have so far
      useChatStore.getState().updateMessageText(id, fullText.slice(0, i));
      useChatStore.getState().markMessageDone(id);
      debug("Aborted");
    };

    if (signal) {
      if (signal.aborted) return onAbort();
      signal.addEventListener("abort", onAbort, { once: true });
    }

    await new Promise<void>((resolve) => {
      const tick = () => {
        if (aborted) return resolve();

        i = Math.min(i + step, length);
        scheduleFlush();

        if (i < length) {
          timerId = window.setTimeout(tick, delay);
        } else {
          resolve();
        }
      };

      timerId = window.setTimeout(tick, delay);
    });

    if (!aborted) finalize();

    if (signal) {
      try {
        signal.removeEventListener("abort", onAbort as any);
      } catch {
        /* no-op */
      }
    }
  };
};
