// File: src/hooks/useStreamText.ts
// Stream text into a message with RAF batching + abort safety
// API unchanged: useStreamText()(id, fullText, signal?, baseDelay?)
import { startTransition } from "react";
import { useChatStore } from "../store/chatStore";
import { STREAM_BATCH_MS } from "../constants/perf"; // ← perf knobs

const FLUSH_FALLBACK_MS = STREAM_BATCH_MS;

export const useStreamText = () => {
  return async (
    id: string,
    fullText: string,
    signal?: AbortSignal,
    baseDelay = STREAM_BATCH_MS // ← default to batch interval
  ): Promise<void> => {
    const { updateMessageText, markMessageDone } = useChatStore.getState();

    const length = fullText.length;
    if (length === 0) {
      startTransition(() => {
        updateMessageText(id, "");
        markMessageDone(id);
      });
      return;
    }

    // Adaptive chunking (keeps your previous step logic)
    let step = 1;
    let delay = baseDelay;
    if (length > 600) {
      step = 4;
    } else if (length > 300) {
      step = 3;
    } else if (length > 150) {
      step = 2;
    }

    // Ensure we never tick faster than the batch interval
    const effectiveDelay = Math.max(delay, STREAM_BATCH_MS);

    let i = 0;
    let aborted = false;

    let rafId: number | null = null;
    let fallbackId: number | null = null;
    let timerId: number | null = null;

    const debug =
      process.env.NODE_ENV !== "production"
        ? (msg: string) => console.debug?.(`[streamText] ${msg} :: id=${id}`)
        : () => {};

    debug(
      `Begin: length=${length}, step=${step}, delay=${effectiveDelay}ms, batch=${STREAM_BATCH_MS}ms`
    );

    const doFlush = () => {
      rafId = null;
      const slice = fullText.slice(0, i);
      // Deprioritize re-render so typing/scroll stays snappy
      startTransition(() => {
        useChatStore.getState().updateMessageText(id, slice);
      });
    };

    const scheduleFlush = () => {
      if (typeof requestAnimationFrame === "function" && rafId == null) {
        rafId = requestAnimationFrame(doFlush);
      } else {
        doFlush();
      }
      // Safety: if RAF is starved, force a flush at batch cadence
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
      startTransition(() => {
        useChatStore.getState().updateMessageText(id, fullText); // final flush
        useChatStore.getState().markMessageDone(id); // stop per-message typing
      });
      debug("Complete (final flush)");
    };

    const onAbort = () => {
      aborted = true;
      clearSchedulers();
      startTransition(() => {
        useChatStore.getState().updateMessageText(id, fullText.slice(0, i));
        useChatStore.getState().markMessageDone(id);
      });
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
          timerId = window.setTimeout(tick, effectiveDelay);
        } else {
          resolve();
        }
      };

      timerId = window.setTimeout(tick, effectiveDelay);
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
