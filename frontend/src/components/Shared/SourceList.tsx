// src/components/Shared/SourceList.tsx
import React from "react";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";

export type LooseSource = {
  title?: string;
  url?: string;
  description?: string;
  snippet?: string;
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

const SourceList: React.FC<Props> = ({ items, tone }) => {
  if (!items?.length) return null;

  const isYT = tone === "youtube";
  const border = isYT ? "border-red-300" : "border-green-300";
  const titleColor = isYT ? "text-red-700" : "text-green-700";

  return (
    <div className={`mt-2 rounded-xl border ${border} bg-white/50 p-2`}>
      <div
        className={`flex items-center gap-2 text-sm font-medium ${titleColor}`}
      >
        {/* function-style icons to avoid TS2786 */}
        {isYT
          ? FaYoutube({ className: "text-red-500", size: 16 })
          : FaGlobeEurope({ className: "text-green-600", size: 16 })}
        <span>{isYT ? "YouTube" : "Web"}</span>
      </div>

      <ul className="pl-5 space-y-0.5 text-sm list-none mt-1">
        {items.map((s, i) => {
          const url = (s.url || "").trim();
          const title = (s.title || url || `Link ${i + 1}`).trim();
          const safe = isSafeHref(url);
          const tooltip = s.description || s.snippet || "";
          return (
            <li key={`${title}-${i}`}>
              {safe ? (
                <a
                  href={url}
                  target="_blank"
                  rel="noopener noreferrer nofollow"
                  className={`${titleColor} underline hover:opacity-80`}
                  title={tooltip}
                >
                  {title}
                </a>
              ) : (
                <span className="opacity-70">{title}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
};

export default SourceList;
export { SourceList };
