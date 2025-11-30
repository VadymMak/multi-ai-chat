// File: src/components/Renderers/MessageRenderer.tsx
import React from "react";
import type { ChatMessage } from "../../types/chat";
import { normalizeKind } from "../../utils/renderKinds";
import MarkdownView from "./MarkdownView";
import PlainView from "./PlainView";
import CodeCard from "./CodeCard";
import PdfChip from "../Attachments/PdfChip";

type Props = {
  message: ChatMessage;
  isTyping?: boolean;
};

// Unwrap ```lang\n...\n``` into { language, code }
function unwrapFenced(block: string): {
  code: string;
  language: string | null;
} {
  const m = block.match(/^```([\w+-]*)\s*\r?\n([\s\S]*?)\r?\n```$/);
  if (m) {
    const lang = (m[1] || "").trim();
    return { code: m[2] ?? "", language: lang || null };
  }
  return { code: block, language: null };
}

// ✅ NEW: Detect Project Builder structure markers
function isProjectBuilderOutput(text: string): boolean {
  const markers = [
    "===PROJECT_STRUCTURE_START===",
    "===FINAL_STRUCTURE_START===",
    "===REVIEW_START===",
    "===PROJECT_STRUCTURE_END===",
    "===FINAL_STRUCTURE_END===",
    "===REVIEW_END===",
    "📋 SETUP COMMANDS:",
    "📦 DEPENDENCIES:",
    "🔗 FILE ORDER:",
    "## 📋 GENERATION CHECKLIST:",
  ];
  return markers.some((marker) => text.includes(marker));
}

const MessageRenderer: React.FC<Props> = ({ message }) => {
  const kind = normalizeKind((message as any)?.render?.kind ?? "markdown");
  const text = message.text ?? "";
  const attachments = message.attachments ?? [];
  const isUser = message.sender === "user";

  const hasMarkers = isProjectBuilderOutput(text);
  console.log("🔍 [MessageRenderer]", {
    sender: message.sender,
    isSummary: (message as any)?.isSummary,
    hasMarkers,
    textLength: text.length,
    textStart: text.substring(0, 80),
  });

  // ✅ NEW: Special rendering for Project Builder output
  // ✅ Special rendering for Project Builder output
  if (hasMarkers) {
    return (
      <div className="space-y-2">
        <div
          className="font-mono text-sm bg-[#1e1e2e] text-[#cdd6f4] p-4 rounded-lg border border-[#45475a] overflow-x-auto"
          style={{
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: "1.6",
          }}
        >
          {text}
        </div>

        {/* Attachments */}
        {attachments.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2">
            {attachments
              .filter((a) => a?.mime === "application/pdf")
              .map((a) => (
                <PdfChip
                  key={a?.id ?? a?.url}
                  status="ready"
                  href={a.url}
                  filename={a.name}
                  sizeBytes={a.size}
                />
              ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* Body */}
      {kind === "markdown" && <MarkdownView text={text} isUser={isUser} />}

      {kind === "plain" && <PlainView text={text} isUser={isUser} />}

      {(kind === "code" || kind === "poem_code") && (
        <CodeCard
          code={unwrapFenced(text).code}
          language={
            (message as any)?.render?.language ?? unwrapFenced(text).language
          }
          filename={(message as any)?.render?.filename ?? null}
        />
      )}

      {/* Attachments (PDF chips first, then other files) */}
      {attachments.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {attachments
            .filter((a) => a?.mime === "application/pdf")
            .map((a) => (
              <PdfChip
                key={a?.id ?? a?.url}
                status="ready"
                href={a.url}
                filename={a.name}
                sizeBytes={a.size}
              />
            ))}

          {attachments
            .filter((a) => a?.mime !== "application/pdf")
            .map((a) => (
              <a
                key={a?.id ?? a?.url}
                href={a.url}
                download={a.name}
                target="_blank"
                rel="noopener noreferrer"
                className="px-2 py-1 rounded-full text-xs border bg-white/70 hover:bg-white transition"
                title={a.name}
              >
                📎 {a.name}
              </a>
            ))}
        </div>
      )}
    </div>
  );
};

export default MessageRenderer;
