// File: src/components/Attachments/SourceList.tsx
import React, { useMemo } from "react";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";

export type LooseSource = {
  title?: string;
  url?: string;
  description?: string; // e.g., YouTube description
  snippet?: string; // e.g., web snippet
  /** Optional extras used by YouTube cards; safe to ignore for generic web. */
  videoId?: string;
  channelTitle?: string;
};

function isSafeHref(href?: string | null) {
  if (!href) return false;
  const lower = href.trim().toLowerCase();
  return (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    lower.startsWith("mailto:") ||
    lower.startsWith("tel:")
  );
}

type Props = {
  items: LooseSource[];
  tone: "youtube" | "web";
};

/** Normalize + dedupe by url (fallback to title), preserve first-seen order. */
function useDeduped(items: LooseSource[]) {
  return useMemo(() => {
    const seen = new Set<string>();
    const out: LooseSource[] = [];

    for (const s of items || []) {
      const title = (s.title || s.url || "").trim();
      const url = (s.url || "").trim();
      const key = (url || title).toLowerCase();
      if (!key || seen.has(key)) continue;
      seen.add(key);
      out.push({ ...s, title, url });
    }
    return out.slice(0, 12);
  }, [items]);
}

const SourceList: React.FC<Props> = ({ items, tone }) => {
  const deduped = useDeduped(items);
  const prefersReduced = useReducedMotion();
  if (!deduped.length) return null;

  const isYT = tone === "youtube";
  const border = isYT ? "border-red-300" : "border-green-300";
  const titleColor = isYT ? "text-red-700" : "text-green-700";
  const icon = isYT
    ? FaYoutube({ className: "text-red-500", size: 16 })
    : FaGlobeEurope({ className: "text-green-600", size: 16 });

  return (
    <motion.div
      initial={{ opacity: 0, y: prefersReduced ? 0 : 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: prefersReduced ? 0 : 0.18 }}
      className={`mt-2 rounded-xl border ${border} bg-white/50 p-2`}
      role="region"
      aria-label={isYT ? "YouTube results" : "Web results"}
      data-source-type={tone}
    >
      <div
        className={`flex items-center gap-2 text-sm font-medium ${titleColor}`}
      >
        {icon}
        <span>{isYT ? "YouTube" : "Web"}</span>
      </div>

      <ul className="mt-2 pl-0 space-y-2 text-sm">
        <AnimatePresence initial={false}>
          {deduped.map((s, i) => {
            const url = s.url || "";
            const safe = isSafeHref(url);
            const label = (s.title || url || `Link ${i + 1}`).trim();
            const metaPieces = [
              s.channelTitle?.trim(), // show channel for YT when available
              (s.description || s.snippet || "").trim(),
            ].filter(Boolean);
            const meta = metaPieces.join(" • ");
            const key = (url || label || String(i)).toLowerCase();

            return (
              <motion.li
                key={key}
                initial={{ opacity: 0, y: prefersReduced ? 0 : 4 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: prefersReduced ? 0 : -4 }}
                transition={{ duration: prefersReduced ? 0 : 0.16 }}
                className="flex flex-col"
              >
                {safe ? (
                  <a
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer external nofollow"
                    title={meta || url}
                    className={`${titleColor} underline hover:opacity-80 truncate`}
                  >
                    {label}
                  </a>
                ) : (
                  <span className="opacity-70 truncate" title={label}>
                    {label}
                  </span>
                )}
                {meta ? (
                  <div className="text-xs text-gray-600 leading-snug line-clamp-2">
                    {meta}
                  </div>
                ) : null}
              </motion.li>
            );
          })}
        </AnimatePresence>
      </ul>
    </motion.div>
  );
};

export default SourceList;
