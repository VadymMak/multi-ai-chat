// src/components/Chat/ChatMessageBubble.tsx
import React, { memo, useMemo } from "react";
import { motion } from "framer-motion";
import type { ChatMessage } from "../../types/chat";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";
import CodeBlock from "../Shared/CodeBlock";
import { MarkdownMessage } from "../Shared/MarkdownMessage";
import MessageRenderer from "../Renderers/MessageRenderer";
import { normalizeKind } from "../../utils/renderKinds";

interface Props {
  message: ChatMessage;
  isLatestAiMessage?: boolean;
}

type StreamSeg =
  | { type: "text"; content: string }
  | { type: "code"; language: string | null; code: string }
  | { type: "openCode"; language: string | null; code: string };

const PHASE_MARKER_TEXT =
  "📌 new phase started after summarization".toLowerCase();

/* ------------------------ stateless helpers ----------------------- */
function splitStreaming(text: string): StreamSeg[] {
  const segs: StreamSeg[] = [];
  let i = 0;
  while (true) {
    const start = text.indexOf("```", i);
    if (start < 0) {
      const rest = text.slice(i);
      if (rest) segs.push({ type: "text", content: rest });
      break;
    }
    if (start > i) segs.push({ type: "text", content: text.slice(i, start) });

    const afterTicks = start + 3;
    let langLineEnd = text.indexOf("\n", afterTicks);
    if (langLineEnd < 0) langLineEnd = text.indexOf("\r\n", afterTicks);
    if (langLineEnd < 0) {
      const langRaw = text.slice(afterTicks).trim();
      segs.push({ type: "openCode", language: langRaw || null, code: "" });
      break;
    }
    const language = text.slice(afterTicks, langLineEnd).trim() || null;

    const closingIdxLF = text.indexOf("\n```", langLineEnd + 1);
    const closingIdxCRLF = text.indexOf("\r\n```", langLineEnd + 1);
    let end = -1;
    if (closingIdxLF >= 0 && closingIdxCRLF >= 0)
      end = Math.min(closingIdxLF, closingIdxCRLF);
    else end = Math.max(closingIdxLF, closingIdxCRLF);

    if (end < 0) {
      const code = text.slice(langLineEnd + 1);
      segs.push({ type: "openCode", language, code });
      break;
    } else {
      const code = text.slice(langLineEnd + 1, end);
      segs.push({ type: "code", language, code });

      const afterFence = text.indexOf("```", end) + 3;
      let nextIndex = afterFence;
      if (text.slice(afterFence, afterFence + 2) === "\r\n")
        nextIndex = afterFence + 2;
      else if (text[afterFence] === "\n") nextIndex = afterFence + 1;
      i = nextIndex;
    }
  }
  return segs;
}

function unwrapSingleFence(block: string): {
  code: string;
  language: string | null;
} {
  const m = block.match(/^```([\w+-]*)\s*\r?\n([\s\S]*?)\r?\n```$/);
  if (m) {
    const lang = m[1]?.trim() || null;
    const code = m[2] ?? "";
    return { code, language: lang || null };
  }
  return { code: block, language: null };
}

/* -------------------------------- component -------------------------------- */
const ChatMessageBubbleBase: React.FC<Props> = ({ message }) => {
  const { sender, text = "", isSummary, isTyping } = message;

  const isUser = sender === "user";
  const isYouTube = sender === "youtube";
  const isWeb = sender === "web";

  // normalized kind (final rendering is delegated to MessageRenderer)
  const kind = useMemo(
    () => normalizeKind(message.render?.kind ?? "markdown"),
    [message.render?.kind]
  );

  const isDivider = useMemo(
    () =>
      (sender === "system" || sender === "final") &&
      (text || "").trim().toLowerCase() === PHASE_MARKER_TEXT,
    [sender, text]
  );

  const containerClass = useMemo(
    () => `flex w-full ${isUser ? "justify-end" : "justify-start"}`,
    [isUser]
  );

  const bubbleClass = useMemo(
    () =>
      [
        "relative px-4 py-3 rounded-2xl max-w-[85%] sm:max-w-[70%]",
        isUser
          ? "bg-blue-600 text-white rounded-br-sm shadow-md"
          : isYouTube
          ? "bg-red-50 text-red-900 rounded-bl-sm border border-red-300 shadow-sm"
          : isWeb
          ? "bg-green-50 text-green-900 rounded-bl-sm border border-green-300 shadow-sm"
          : isSummary || sender === "final"
          ? "bg-violet-50 text-violet-900 rounded-bl-sm shadow-sm"
          : "bg-gray-100 text-gray-900 rounded-bl-sm shadow-md",
      ].join(" "),
    [isUser, isYouTube, isWeb, isSummary, sender]
  );

  const senderLabel = useMemo(() => {
    if (isYouTube) {
      return (
        <>
          {FaYoutube({ className: "text-red-500", size: 16 })}
          <span>📺 YouTube Insight</span>
        </>
      );
    }
    if (isWeb) {
      return (
        <>
          {FaGlobeEurope({ className: "text-green-600", size: 16 })}
          <span>🌐 Web Insight</span>
        </>
      );
    }
    if (isSummary || sender === "final") {
      return (
        <>
          {getModelIcon("anthropic")}
          <span className="font-serif italic text-[17px] text-violet-800">
            ✅ Final Answer by <strong>Claude</strong>
          </span>
        </>
      );
    }
    if (sender === "openai") {
      return (
        <>
          {getModelIcon("openai")}
          <span className="text-blue-700 font-medium">💡 OpenAI</span>
        </>
      );
    }
    if (sender === "anthropic") {
      return (
        <>
          {getModelIcon("anthropic")}
          <span className="text-violet-700 font-medium">🤖 Claude</span>
        </>
      );
    }
    if (sender === "assistant") {
      // ✅ New: generic assistant label (some BE rows use this)
      return <span className="text-gray-600 font-medium">🤖 Assistant</span>;
    }
    return null;
  }, [isYouTube, isWeb, isSummary, sender]);

  // Pre-split streaming markdown only when text/kind change
  const streamingSegments = useMemo(
    () => (kind === "markdown" ? splitStreaming(text) : []),
    [text, kind]
  );

  const renderStreaming = () => {
    if (kind === "code" || kind === "poem_code") {
      const unwrapped = unwrapSingleFence(text);
      const language = message.render?.language ?? unwrapped.language ?? null;
      return (
        <CodeBlock
          code={unwrapped.code}
          language={language}
          filename={message.render?.filename ?? null}
        />
      );
    }

    if (kind === "plain" || kind === "poem_plain") {
      return <MarkdownMessage text={text} isUser={isUser} kind={kind} />;
    }

    // markdown → split while streaming
    if (streamingSegments.length === 0) {
      return <MarkdownMessage text={text} isUser={isUser} kind={kind} />;
    }
    return (
      <div className="space-y-2">
        {streamingSegments.map((seg, idx) => {
          if (seg.type === "text") {
            return (
              <MarkdownMessage
                key={`t-${idx}`}
                text={seg.content}
                isUser={isUser}
                kind={kind}
              />
            );
          }
          if (seg.type === "code") {
            return (
              <CodeBlock
                key={`c-${idx}`}
                code={seg.code}
                language={seg.language}
              />
            );
          }
          // openCode (no closing fence yet)
          return (
            <div key={`o-${idx}`} className="relative">
              <pre className="my-2 rounded-2xl overflow-x-auto border border-blue-200 bg-blue-50 p-3 animate-pulse">
                <code className="font-mono text-[13.5px] leading-[1.45] text-slate-900 whitespace-pre">
                  {seg.code || " "}
                </code>
              </pre>
              <span className="absolute -top-2 right-3 text-[10px] px-1.5 py-0.5 rounded-full bg-blue-500 text-white shadow">
                typing…
              </span>
            </div>
          );
        })}
      </div>
    );
  };

  if (isDivider) {
    return (
      <div className="flex items-center justify-center my-4">
        <div className="border-t border-gray-300 flex-grow mr-2" />
        <span className="text-xs text-gray-500 font-medium">
          📌 New Phase Started After Summarization
        </span>
        <div className="border-t border-gray-300 flex-grow ml-2" />
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={containerClass}
    >
      <div className={bubbleClass}>
        {!isUser && senderLabel && (
          <div className="flex items-center gap-2 mb-1 text-sm text-gray-500">
            {senderLabel}
          </div>
        )}

        <div
          className={`text-sm break-words ${
            isSummary ? "text-violet-900 font-serif" : ""
          }`}
        >
          {isTyping ? renderStreaming() : <MessageRenderer message={message} />}
        </div>

        {isTyping && (
          <div className="mt-1 animate-pulse text-sm text-gray-400">
            Typing...
          </div>
        )}
      </div>
    </motion.div>
  );
};

// Only re-render when meaningful parts of the message changed
const propsEqual = (a: Props, b: Props) => {
  const ma = a.message;
  const mb = b.message;
  return (
    a.isLatestAiMessage === b.isLatestAiMessage &&
    ma.id === mb.id &&
    ma.sender === mb.sender &&
    (ma.text ?? "") === (mb.text ?? "") &&
    (ma.isTyping ?? false) === (mb.isTyping ?? false) &&
    (ma.isSummary ?? false) === (mb.isSummary ?? false) &&
    (ma.render?.kind ?? "markdown") === (mb.render?.kind ?? "markdown") &&
    (ma.render?.language ?? null) === (mb.render?.language ?? null) &&
    (ma.render?.filename ?? null) === (mb.render?.filename ?? null)
  );
};

export default memo(ChatMessageBubbleBase, propsEqual);
