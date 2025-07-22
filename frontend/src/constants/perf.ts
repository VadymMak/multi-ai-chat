// File: src/constants/perf.ts

/**
 * Streaming & scrolling perf knobs
 *
 * You can override these at runtime:
 *   localStorage.setItem('perf:STREAM_BATCH_MS', '48')
 *   localStorage.setItem('perf:SCROLL_FINAL_DEBOUNCE', '0')
 *
 * Or via env (CRA):
 *   REACT_APP_STREAM_BATCH_MS=48
 *   REACT_APP_SCROLL_FINAL_DEBOUNCE=0
 */

type Clamp = { min?: number; max?: number };

const readOverrideNumber = (
  lsKey: string,
  envKey: string,
  fallback: number,
  clamp?: Clamp
): number => {
  let raw: string | null | undefined;

  // 1) localStorage (highest priority)
  if (typeof window !== "undefined" && window.localStorage) {
    try {
      raw = window.localStorage.getItem(lsKey);
    } catch {
      /* ignore storage errors */
    }
  }

  // 2) process.env (CRA - REACT_APP_*)
  if (!raw && typeof process !== "undefined" && (process as any).env) {
    // @ts-ignore - CRA defines process.env at build time
    raw = (process.env as Record<string, string | undefined>)[envKey];
  }

  const n = Number(raw);
  let out = Number.isFinite(n) ? Math.round(n) : fallback;

  // Optional clamp
  if (clamp?.min != null && out < clamp.min) out = clamp.min;
  if (clamp?.max != null && out > clamp.max) out = clamp.max;

  return out;
};

// How long to wait before a forced flush if RAF hasn't run yet.
// 16–48ms is typically a sweet spot. We clamp to [8, 120] just in case.
export const STREAM_BATCH_MS = readOverrideNumber(
  "perf:STREAM_BATCH_MS",
  "REACT_APP_STREAM_BATCH_MS",
  32,
  { min: 8, max: 120 }
);

// Delay before doing the final smooth scroll to bottom after streaming ends.
// 0 = immediate. Clamp to [0, 1000] to avoid silly values.
export const SCROLL_FINAL_DEBOUNCE = readOverrideNumber(
  "perf:SCROLL_FINAL_DEBOUNCE",
  "REACT_APP_SCROLL_FINAL_DEBOUNCE",
  0,
  { min: 0, max: 1000 }
);
