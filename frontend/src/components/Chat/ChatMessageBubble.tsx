// File: src/components/Chat/ChatMessageBubble.tsx
import React from "react";
import { motion } from "framer-motion";
import type { ChatMessage } from "../../types/chat";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";
import CodeBlock from "../Shared/CodeBlock";
import { MarkdownMessage } from "../Shared/MarkdownMessage";
import SourceList, { LooseSource } from "../Shared/SourceList";
import type { RenderKind } from "../../types/chat";

interface Props {
  message: ChatMessage;
  isLatestAiMessage?: boolean;
}

type StreamSeg =
  | { type: "text"; content: string }
  | { type: "code"; language: string | null; code: string }
  | { type: "openCode"; language: string | null; code: string };

const DEBUG = false;

/** Split streaming text by fenced code blocks (robust to \r\n) */
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

    // Find end of the language line
    const afterTicks = start + 3;
    let langLineEnd = text.indexOf("\n", afterTicks);
    if (langLineEnd < 0) langLineEnd = text.indexOf("\r\n", afterTicks);
    if (langLineEnd < 0) {
      const langRaw = text.slice(afterTicks).trim();
      segs.push({ type: "openCode", language: langRaw || null, code: "" });
      break;
    }
    const language = text.slice(afterTicks, langLineEnd).trim() || null;

    // Find the closing fence
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

      // advance index past "\n```" or "\r\n```" and the trailing newline after fence
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

/** If the whole message is code (render.kind === "code"), strip outer ``` fences */
function unwrapSingleFence(block: string): {
  code: string;
  language: string | null;
} {
  // ^```lang?\r?\n([\s\S]*?)\r?\n```$
  const m = block.match(/^```([\w+-]*)\s*\r?\n([\s\S]*?)\r?\n```$/);
  if (m) {
    const lang = m[1]?.trim() || null;
    const code = m[2] ?? "";
    return { code, language: lang || null };
  }
  return { code: block, language: null };
}

const ChatMessageBubble: React.FC<Props> = ({ message }) => {
  const { sender, text = "", isSummary, isTyping } = message;

  const isUser = sender === "user";
  const isYouTube = sender === "youtube";
  const isWeb = sender === "web";

  const showLabel = !isUser;

  // Primary render policy (normalized by aiApi.normalizeRenderMeta)
  // Safety fallback: if server sent {render:{type:"doc"}} without kind, treat as markdown.
  const normalizedKind: RenderKind | undefined = (message as any)?.render?.kind;
  const serverType = (message as any)?.render?.type;
  const kind: RenderKind =
    normalizedKind ??
    (serverType === "doc" ? "markdown" : undefined) ??
    (isYouTube || isWeb ? "plain" : "markdown");

  if (DEBUG) {
    console.log("🧪 bubble", {
      id: message.id,
      sender: message.sender,
      kind,
      serverType,
      language: message.render?.language ?? null,
      filename: message.render?.filename ?? null,
      hasFences: /```/.test(text),
      preview: text.slice(0, 120),
    });
  }

  // Unified sources
  const sources: any = (message as any)?.sources || {};
  const youtubeItemsFromMsg = React.useMemo<LooseSource[]>(
    () =>
      (Array.isArray(sources?.youtube)
        ? sources.youtube
        : (message as any).youtube) ?? [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(sources?.youtube), JSON.stringify((message as any).youtube)]
  );
  const webItemsFromMsg = React.useMemo<LooseSource[]>(
    () =>
      (Array.isArray(sources?.web) ? sources.web : (message as any).web) ?? [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [JSON.stringify(sources?.web), JSON.stringify((message as any).web)]
  );

  const getSenderLabel = () => {
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
    if (isSummary) {
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
    return null;
  };

  /** Streaming content — respect render kind */
  const streamingContent = React.useMemo(() => {
    // Code & poem_code: single code block while streaming
    if (kind === "code" || kind === "poem_code") {
      const unwrapped = unwrapSingleFence(text);
      const language =
        (message as any)?.render?.language ?? unwrapped.language ?? null;
      return (
        <CodeBlock
          code={unwrapped.code}
          language={language}
          filename={(message as any)?.render?.filename ?? null}
        />
      );
    }

    // Plain / poem_plain: render without forcing fenced splitting
    if (kind === "plain" || kind === "poem_plain") {
      return <MarkdownMessage text={text} isUser={isUser} kind={kind} />;
    }

    // Markdown: split fences for smoother stream
    const segs = splitStreaming(text);
    if (segs.length === 0) {
      return <MarkdownMessage text={text} isUser={isUser} kind={kind} />;
    }
    return (
      <div className="space-y-2">
        {segs.map((seg: StreamSeg, idx: number) => {
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
  }, [text, isUser, kind, message]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`relative px-4 py-3 rounded-2xl max-w-[85%] sm:max-w-[70%]
        ${
          isUser
            ? "bg-blue-600 text-white rounded-br-sm shadow-md"
            : isYouTube
            ? "bg-red-50 text-red-900 rounded-bl-sm border border-red-300 shadow-sm"
            : isWeb
            ? "bg-green-50 text-green-900 rounded-bl-sm border border-green-300 shadow-sm"
            : isSummary
            ? "bg-violet-50 text-violet-900 rounded-bl-sm shadow-sm"
            : "bg-gray-100 text-gray-900 rounded-bl-sm shadow-md"
        }`}
      >
        {showLabel && (
          <div className="flex items-center gap-2 mb-1 text-sm text-gray-500">
            {getSenderLabel()}
          </div>
        )}

        <div
          className={`text-sm break-words ${
            isSummary ? "text-violet-900 font-serif" : ""
          }`}
        >
          {/* Same renderer in both states to avoid layout jump */}
          {isTyping ? (
            streamingContent
          ) : kind === "code" || kind === "poem_code" ? (
            (() => {
              const unwrapped = unwrapSingleFence(text);
              const language =
                (message as any)?.render?.language ??
                unwrapped.language ??
                null;
              return (
                <CodeBlock
                  code={unwrapped.code}
                  language={language}
                  filename={(message as any)?.render?.filename ?? null}
                />
              );
            })()
          ) : (
            <MarkdownMessage text={text} isUser={isUser} kind={kind} />
          )}
        </div>

        {isTyping && (
          <div className="mt-1 animate-pulse text-sm text-gray-400">
            Typing...
          </div>
        )}

        {/* Supplementary cards only for assistant messages that aren't already YT/Web bubbles */}
        {!isUser && !isYouTube && youtubeItemsFromMsg.length > 0 && (
          <SourceList items={youtubeItemsFromMsg} tone="youtube" />
        )}
        {!isUser && !isWeb && webItemsFromMsg.length > 0 && (
          <SourceList items={webItemsFromMsg} tone="web" />
        )}
      </div>
    </motion.div>
  );
};

export default ChatMessageBubble;
