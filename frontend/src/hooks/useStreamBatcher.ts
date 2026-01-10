// File: src/hooks/useStreamBatcher.ts
import { useRef, useEffect, useCallback, startTransition } from "react";
import { STREAM_BATCH_MS } from "../constants/perf";

export function useStreamBatcher<T>(
  onFlush: (items: T[]) => void,
  batchMs = STREAM_BATCH_MS
) {
  const q = useRef<T[]>([]);
  const rafId = useRef<number | null>(null);
  const timeoutId = useRef<number | null>(null);
  const flushing = useRef(false);
  const disposed = useRef(false);

  const flush = useCallback(() => {
    if (flushing.current) return;
    flushing.current = true;
    const items = q.current.splice(0);
    if (items.length) {
      // Deprioritize UI work to keep typing/scroll smooth
      startTransition(() => onFlush(items));
    }
    flushing.current = false;
  }, [onFlush]);

  const schedule = useCallback(() => {
    if (disposed.current) return;

    // Try to align with the paint loop
    if (rafId.current == null && typeof requestAnimationFrame === "function") {
      rafId.current = requestAnimationFrame(() => {
        rafId.current = null;
        flush();
      });
    }

    // Safety fallback if RAF is starved; never faster than STREAM_BATCH_MS
    if (timeoutId.current == null) {
      const delay = Math.max(8, Math.min(batchMs, STREAM_BATCH_MS));
      timeoutId.current = window.setTimeout(() => {
        timeoutId.current = null;
        flush();
      }, delay);
    }
  }, [batchMs, flush]);

  const push = useCallback(
    (item: T) => {
      q.current.push(item);
      schedule();
    },
    [schedule]
  );

  const flushNow = useCallback(() => {
    if (rafId.current != null && typeof cancelAnimationFrame === "function") {
      cancelAnimationFrame(rafId.current);
    }
    if (timeoutId.current != null) {
      clearTimeout(timeoutId.current);
    }
    rafId.current = null;
    timeoutId.current = null;
    flush();
  }, [flush]);

  useEffect(() => {
    return () => {
      disposed.current = true;
      if (rafId.current != null && typeof cancelAnimationFrame === "function") {
        cancelAnimationFrame(rafId.current);
      }
      if (timeoutId.current != null) clearTimeout(timeoutId.current);
      q.current = [];
    };
  }, []);

  return { push, flushNow };
}
