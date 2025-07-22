import { useRef, useCallback } from "react";
import { SCROLL_FINAL_DEBOUNCE } from "../constants";

export function useAutoScroll<T extends HTMLElement>(containerRef: {
  current: T | null;
}) {
  const scheduled = useRef(false);

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
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const doScroll = () =>
      el.scrollTo({
        top: el.scrollHeight,
        behavior: prefersReduced ? "auto" : "smooth",
      });

    if (SCROLL_FINAL_DEBOUNCE > 0) {
      setTimeout(doScroll, SCROLL_FINAL_DEBOUNCE);
    } else {
      doScroll();
    }
  }, [containerRef]);

  return { duringStream, onFinal };
}
