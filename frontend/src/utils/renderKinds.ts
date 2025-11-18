// src/utils/renderKinds.ts
import type { RenderKind } from "../types/chat";

/** Optional: reuse these in InputBar so we don't duplicate types */
export type OutputMode = "doc" | "plain" | "code";
export type Presentation = "default" | "poem_plain" | "poem_code";

/** Canonical list & guard */
export const RENDER_KINDS: RenderKind[] = [
  "markdown",
  "plain",
  "code",
  "poem_plain",
  "poem_code",
];

export function isRenderKind(x: unknown): x is RenderKind {
  return typeof x === "string" && (RENDER_KINDS as string[]).includes(x);
}

/** Accepts loose inputs and normalizes to a valid RenderKind (default: markdown) */
export function normalizeKind(
  raw?: string | null,
  fallback: RenderKind = "markdown"
): RenderKind {
  if (!raw) return fallback;
  const s = String(raw).trim().toLowerCase();
  switch (s) {
    case "md":
    case "doc":
    case "markdown":
      return "markdown";
    case "txt":
    case "text":
    case "plain":
      return "plain";
    case "code":
      return "code";
    case "poem":
    case "poem_plain":
      return "poem_plain";
    case "poem-code":
    case "poem_code":
      return "poem_code";
    default:
      return isRenderKind(s as RenderKind) ? (s as RenderKind) : fallback;
  }
}

/** UI state → canonical RenderKind */
export function toRenderKind(
  mode: OutputMode,
  presentation: Presentation
): RenderKind {
  if (mode === "code" && presentation === "poem_code") return "poem_code";
  if (mode === "plain" && presentation === "poem_plain") return "poem_plain";
  if (mode === "code") return "code";
  if (mode === "plain") return "plain";
  return "markdown"; // "doc"
}

/** Canonical RenderKind → UI state (useful for toggles) */
export function fromRenderKind(
  kind: RenderKind
): { mode: OutputMode; presentation: Presentation } {
  switch (normalizeKind(kind)) {
    case "plain":
      return { mode: "plain", presentation: "default" };
    case "code":
      return { mode: "code", presentation: "default" };
    case "poem_plain":
      return { mode: "plain", presentation: "poem_plain" };
    case "poem_code":
      return { mode: "code", presentation: "poem_code" };
    case "markdown":
    default:
      return { mode: "doc", presentation: "default" };
  }
}

/** Helpers */
export const isCodeLike = (k?: RenderKind) =>
  normalizeKind(k) === "code" || normalizeKind(k) === "poem_code";

export const isPlainLike = (k?: RenderKind) =>
  normalizeKind(k) === "plain" || normalizeKind(k) === "poem_plain";

export const isPoem = (k?: RenderKind) =>
  normalizeKind(k) === "poem_plain" || normalizeKind(k) === "poem_code";

/** Content-Type hint (handy for headers/attachments) */
export function kindToContentType(
  kind: RenderKind,
  language?: string | null,
  filename?: string | null
): string {
  const k = normalizeKind(kind);
  if (k === "markdown") return "text/markdown; charset=utf-8";
  if (k === "plain" || k === "poem_plain") return "text/plain; charset=utf-8";
  if (k === "code" || k === "poem_code") {
    const lang = language ? `; lang=${encodeURIComponent(language)}` : "";
    const file = filename ? `; filename=${encodeURIComponent(filename)}` : "";
    return `text/x-code${lang}${file}; charset=utf-8`;
  }
  return "text/plain; charset=utf-8";
}

/** Nice labels for UI (optional) */
export const RENDER_KIND_LABELS: Record<RenderKind, string> = {
  markdown: "Markdown",
  plain: "Plain",
  code: "Code",
  poem_plain: "Poem · plain",
  poem_code: "Poem · code",
};
