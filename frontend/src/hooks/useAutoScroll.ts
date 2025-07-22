// File: src/hooks/useAutoScroll.ts
import { useRef, useCallback, useEffect } from "react";
import { SCROLL_FINAL_DEBOUNCE } from "../constants/perf";

export function useAutoScroll<T extends HTMLElement>(containerRef: {
  current: T | null;
}) {
  const scheduled = useRef(false);
  const finalTimerRef = useRef<number | null>(null);

  const duringStream = useCallback(() => {
    if (scheduled.current) return;
    scheduled.current = true;
    requestAnimationFrame(() => {
      scheduled.current = false;
      const el = containerRef.current;
      if (!el) return;
      el.scrollTop = el.scrollHeight;
    });
  }, [containerRef]);

  const onFinal = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;

    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches;

    const doScroll = () => {
      // Double RAF to let layout settle before smooth scroll
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          el.scrollTo({
            top: el.scrollHeight,
            behavior: prefersReduced ? "auto" : "smooth",
          });
        });
      });
    };

    if (finalTimerRef.current) window.clearTimeout(finalTimerRef.current);
    if (SCROLL_FINAL_DEBOUNCE > 0) {
      finalTimerRef.current = window.setTimeout(
        doScroll,
        SCROLL_FINAL_DEBOUNCE
      );
    } else {
      doScroll();
    }
  }, [containerRef]);

  useEffect(() => {
    return () => {
      if (finalTimerRef.current) window.clearTimeout(finalTimerRef.current);
    };
  }, []);

  return { duringStream, onFinal };
}
