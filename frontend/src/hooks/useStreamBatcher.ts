import { useRef, useEffect, useCallback } from "react";

export function useStreamBatcher<T>(
  onFlush: (items: T[]) => void,
  batchMs = 32
) {
  const q = useRef<T[]>([]);
  const raf = useRef<number | null>(null);
  const t = useRef<number | null>(null);
  const flushing = useRef(false);

  const flush = useCallback(() => {
    if (flushing.current) return;
    flushing.current = true;
    const items = q.current.splice(0);
    if (items.length) onFlush(items);
    flushing.current = false;
  }, [onFlush]);

  const schedule = useCallback(() => {
    if (raf.current == null) {
      raf.current = requestAnimationFrame(() => {
        raf.current = null;
        flush();
      });
    }
    if (t.current == null) {
      t.current = window.setTimeout(() => {
        t.current = null;
        flush();
      }, batchMs);
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
    if (raf.current) cancelAnimationFrame(raf.current);
    if (t.current) clearTimeout(t.current);
    raf.current = null;
    t.current = null;
    flush();
  }, [flush]);

  useEffect(
    () => () => {
      if (raf.current) cancelAnimationFrame(raf.current);
      if (t.current) clearTimeout(t.current);
    },
    []
  );

  return { push, flushNow };
}
