// src/components/Chat/ChatMessageBubble.tsx
import React, { memo, useMemo } from "react";
import { motion } from "framer-motion";
import type { ChatMessage } from "../../types/chat";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";
import { Clock } from "lucide-react";
import MessageActions from "./MessageActions";
import CodeBlock from "../Shared/CodeBlock";
import MarkdownMessage from "../Shared/MarkdownMessage";
import MessageRenderer from "../Renderers/MessageRenderer";
import { AttachmentPreview } from "./AttachmentPreview";
import { normalizeKind } from "../../utils/renderKinds";
import { useChatStore } from "../../store/chatStore";

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

// Форматирование времени
function formatTimestamp(timestamp?: string): string {
  if (!timestamp) return "";

  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;

  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;

  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}

// Цветные аватары для AI моделей
function getAvatarStyles(sender: string): {
  bg: string;
  text: string;
  icon: string;
} {
  switch (sender) {
    case "openai":
      return {
        bg: "bg-green-500/20",
        text: "text-green-500",
        icon: "🟢",
      };
    case "anthropic":
      return {
        bg: "bg-purple-500/20",
        text: "text-purple-500",
        icon: "🟣",
      };
    case "youtube":
      return {
        bg: "bg-red-500/20",
        text: "text-red-500",
        icon: "🔴",
      };
    case "web":
      return {
        bg: "bg-blue-500/20",
        text: "text-blue-500",
        icon: "🔵",
      };
    case "user":
      return {
        bg: "bg-gray-500/20",
        text: "text-gray-500",
        icon: "👤",
      };
    default:
      return {
        bg: "bg-gray-500/20",
        text: "text-gray-500",
        icon: "🤖",
      };
  }
}

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
  const { sender, text = "", isSummary, isTyping, timestamp } = message;

  const displayTimestamp = timestamp || new Date().toISOString();

  // ✅ Edit mode state
  const [isEditing, setIsEditing] = React.useState(false);
  const [editedText, setEditedText] = React.useState(text);

  const handleEdit = () => {
    setIsEditing(true);
    setEditedText(text);
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditedText(text);
  };

  const handleSaveEdit = async () => {
    if (editedText.trim() === "") {
      alert("Message cannot be empty!");
      return;
    }

    try {
      await useChatStore
        .getState()
        .updateMessageOnServer(message.id || "", editedText);
      setIsEditing(false);
    } catch (error) {
      console.error("Save edit failed:", error);
    }
  };

  const handleRegenerate = async () => {
    if (!window.confirm("Regenerate this AI response?")) return;

    try {
      await useChatStore.getState().regenerateMessageOnServer(message.id || "");
    } catch (error) {
      console.error("Regenerate failed:", error);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm("Are you sure you want to delete this message?"))
      return;

    try {
      await useChatStore.getState().deleteMessageOnServer(message.id || "");
    } catch (error) {
      console.error("Delete failed:", error);
    }
  };

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
    () => `flex w-full mb-6 ${isUser ? "justify-end" : "justify-start"}`,
    [isUser]
  );

  const bubbleClass = useMemo(
    () =>
      [
        "group relative px-5 py-4 max-w-[85%] sm:max-w-[70%] rounded-lg shadow-sm",
        isUser
          ? "bg-surface text-text-primary border-l-[4px] border-l-primary"
          : isYouTube
          ? "bg-surface text-text-primary border-l-[4px] border-l-error"
          : isWeb
          ? "bg-surface text-text-primary border-l-[4px] border-l-success"
          : isSummary || sender === "final"
          ? "bg-panel text-text-primary border-l-[4px] border-l-purple"
          : "bg-panel text-text-primary border-l-[4px] border-l-success",
      ].join(" "),
    [isUser, isYouTube, isWeb, isSummary, sender]
  );

  const senderLabel = useMemo(() => {
    if (isYouTube) {
      return (
        <>
          {FaYoutube({ className: "text-error", size: 16 })}
          <span>📺 YouTube Insight</span>
        </>
      );
    }
    if (isWeb) {
      return (
        <>
          {FaGlobeEurope({ className: "text-success", size: 16 })}
          <span>🌐 Web Insight</span>
        </>
      );
    }
    if (isSummary || sender === "final") {
      return (
        <>
          {getModelIcon("anthropic")}
          <span className="font-serif italic text-[17px] text-success">
            ✅ Final Answer by <strong>Claude</strong>
          </span>
        </>
      );
    }
    if (sender === "openai") {
      return (
        <>
          {getModelIcon("openai")}
          <span className="text-primary font-medium">💡 OpenAI</span>
        </>
      );
    }
    if (sender === "anthropic") {
      return (
        <>
          {getModelIcon("anthropic")}
          <span className="text-success font-medium">🤖 Claude</span>
        </>
      );
    }
    if (sender === "assistant") {
      // ✅ New: generic assistant label (some BE rows use this)
      return (
        <span className="text-text-secondary font-medium">🤖 Assistant</span>
      );
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
              <pre className="my-2 rounded overflow-x-auto border border-border bg-surface p-3 animate-pulse">
                <code className="font-mono text-[13.5px] leading-[1.45] text-text-primary whitespace-pre">
                  {seg.code || " "}
                </code>
              </pre>
              <span className="absolute -top-2 right-3 text-[10px] px-1.5 py-0.5 rounded bg-primary text-text-primary">
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
        <div className="border-t border-border flex-grow mr-2" />
        <span className="text-xs text-text-secondary font-medium">
          📌 New Phase Started After Summarization
        </span>
        <div className="border-t border-border flex-grow ml-2" />
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
          <div className="flex items-center justify-between mb-3 pb-2 border-b border-border/20">
            <div className="flex items-center gap-2">
              {/* Аватар */}
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-base ${
                  getAvatarStyles(sender).bg
                }`}
              >
                {getAvatarStyles(sender).icon}
              </div>

              {/* Имя модели */}
              <div className="text-sm">{senderLabel}</div>
            </div>

            {/* Timestamp и Message Actions */}
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-1 text-xs text-text-secondary">
                <Clock size={12} />
                {formatTimestamp(displayTimestamp)}
              </div>

              {/* Message Actions Component */}
              <MessageActions
                messageId={message.id || ""}
                content={text}
                role={isUser ? "user" : "assistant"}
                onEdit={isUser ? () => handleEdit() : undefined}
                onRegenerate={!isUser ? () => handleRegenerate() : undefined}
                onDelete={() => handleDelete()}
              />
            </div>
          </div>
        )}

        {isUser && (
          <div className="flex items-center justify-end mb-2 gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
            <div className="flex items-center gap-1 text-xs text-text-secondary">
              <Clock size={12} />
              {formatTimestamp(displayTimestamp)}
            </div>

            <MessageActions
              messageId={message.id || ""}
              content={text}
              role="user"
              onEdit={() => handleEdit()}
              onDelete={() => handleDelete()}
            />
          </div>
        )}

        <div
          className={`text-sm break-words ${
            isSummary ? "text-text-primary font-serif" : ""
          }`}
        >
          {isEditing ? (
            // ✅ EDIT MODE
            <div className="space-y-2">
              <textarea
                value={editedText}
                onChange={(e) => setEditedText(e.target.value)}
                className="w-full min-h-[100px] p-3 bg-surface border border-border rounded-lg text-sm text-text-primary focus:outline-none focus:border-primary resize-y font-mono"
                autoFocus
              />
              <div className="flex items-center gap-2 justify-end">
                <button
                  onClick={handleCancelEdit}
                  className="px-3 py-1.5 text-sm text-text-secondary hover:text-text-primary transition rounded"
                >
                  Cancel
                </button>
                <button
                  onClick={handleSaveEdit}
                  className="px-4 py-1.5 text-sm bg-primary text-white rounded-lg hover:opacity-90 transition"
                >
                  Save
                </button>
              </div>
            </div>
          ) : (
            // ✅ NORMAL MODE
            <>
              {isTyping ? (
                renderStreaming()
              ) : (
                <MessageRenderer message={message} />
              )}
            </>
          )}
        </div>

        {/* ✅ ATTACHMENTS SECTION */}
        {!isEditing &&
          message.attachments &&
          message.attachments.length > 0 && (
            <div className="mt-3 space-y-2">
              {message.attachments.map((attachment) => (
                <AttachmentPreview
                  key={attachment.id}
                  attachment={attachment}
                  onDownload={() => {
                    console.log("Downloading:", attachment);
                  }}
                />
              ))}
            </div>
          )}

        {/* ✅ ENHANCED STREAMING INDICATOR */}
        {message.isStreaming && (
          <div className="mt-2 p-3 bg-blue-50 dark:bg-blue-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
            <div className="flex items-center gap-3">
              <div className="relative">
                <div className="animate-spin text-2xl">⚙️</div>
                <div className="absolute inset-0 animate-ping opacity-20">
                  ⚙️
                </div>
              </div>
              <div className="flex-1">
                <div className="text-sm text-blue-600 dark:text-blue-400 font-medium">
                  Generating code...
                </div>
                <div className="text-xs text-blue-500 dark:text-blue-500 mt-0.5">
                  This may take 1-2 minutes for large projects
                </div>
              </div>
            </div>

            {/* Progress bar */}
            <div className="mt-2 h-1 bg-blue-200 dark:bg-blue-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 animate-pulse"
                style={{ width: "60%" }}
              />
            </div>
          </div>
        )}

        {isTyping && !message.isStreaming && (
          <div className="mt-1 animate-pulse text-sm text-text-secondary">
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
