// File: src/components/Chat/WebSearchResults.tsx
import React, { useMemo } from "react";
import type { ChatMessage } from "../../types/chat";
import SourceList, { LooseSource } from "../Attachments/SourceList";

type Props = { message: ChatMessage };

const mdLink = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/i;
const bareUrl = /(https?:\/\/[^\s)]+)$/i;

function parseLineToSource(line: string): LooseSource | null {
  const s = line.trim().replace(/^[-*•]\s+/, "");
  const m = s.match(mdLink);
  if (m) return { title: m[1], url: m[2] };
  const u = s.match(bareUrl);
  if (u) return { title: u[1], url: u[1] };
  return null;
}

function toLooseSource(v: unknown): LooseSource | null {
  if (!v) return null;

  if (typeof v === "string") {
    const asLine = parseLineToSource(v);
    if (asLine) return asLine;

    // Try "Title - Snippet" (no URL): ignore
    return null;
  }

  const o = v as Record<string, unknown>;
  const rawTitle =
    (typeof o.title === "string" && o.title) ||
    (typeof o.name === "string" && o.name) ||
    "";
  const rawUrl =
    (typeof o.url === "string" && o.url) ||
    (typeof o.link === "string" && o.link) ||
    "";
  const snippet =
    (typeof o.snippet === "string" && o.snippet) ||
    (typeof o.description === "string" && o.description) ||
    undefined;

  const title = (rawTitle || rawUrl).trim();
  const url = rawUrl.trim();
  if (!url) return null;
  return { title, url, snippet };
}

function uniqByUrl(items: LooseSource[]): LooseSource[] {
  const seen = new Set<string>();
  const out: LooseSource[] = [];
  for (const it of items) {
    const key = (it.url || "").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(it);
  }
  return out;
}

const WebSearchResults: React.FC<Props> = ({ message }) => {
  const items = useMemo<LooseSource[]>(() => {
    // Prefer normalized sources → message.sources.web
    const structured =
      ((message as any)?.sources?.web as unknown[]) ||
      ((message as any)?.web as unknown[]) ||
      [];

    if (Array.isArray(structured) && structured.length) {
      return uniqByUrl(
        structured
          .map(toLooseSource)
          .filter((x): x is LooseSource => !!x && (!!x.title || !!x.url))
      );
    }

    // Fallback: parse message.text lines
    const lines =
      message.text
        ?.split("\n")
        .map((l) => l.trim())
        .filter(Boolean) || [];

    return uniqByUrl(
      lines.map(parseLineToSource).filter((x): x is LooseSource => !!x)
    );
  }, [message]);

  if (!items.length) return null;
  return <SourceList tone="web" items={items} />;
};

export default WebSearchResults;
