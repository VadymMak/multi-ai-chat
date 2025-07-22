import React from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { ChatMessage } from "../../types/chat";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaYoutube, FaGlobeEurope } from "react-icons/fa";

interface Props {
  message: ChatMessage;
  isLatestAiMessage?: boolean;
}

const ChatMessageBubble: React.FC<Props> = ({ message }) => {
  const { sender, text = "", isSummary, isTyping } = message;

  const isUser = sender === "user";
  const isYouTube = sender === "youtube";
  const isWeb = sender === "web";

  const isYouTubeFallback =
    isYouTube && text.includes("No specific results found");
  const isWebFallback =
    isWeb && text.includes("No specific Wikipedia results found");

  const showLabel = !isUser && !isYouTubeFallback;

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

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`relative px-4 py-3 rounded-2xl max-w-[85%] sm:max-w-[70%] whitespace-pre-wrap leading-tight
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
          className={`text-sm leading-tight break-words ${
            isSummary ? "text-violet-900 font-serif" : ""
          }`}
        >
          <ReactMarkdown
            components={{
              p: ({ node, ...props }) => <p className="mb-2" {...props} />,
              a: ({ children, ...props }) => (
                <a
                  className={`underline ${
                    isUser
                      ? "text-blue-200 hover:text-white"
                      : "text-blue-600 hover:text-blue-800"
                  }`}
                  target="_blank"
                  rel="noopener noreferrer"
                  {...props}
                >
                  {children}
                </a>
              ),
              code: ({ ...props }) => (
                <code
                  className="bg-gray-200 px-1 py-0.5 rounded text-xs font-mono"
                  {...props}
                />
              ),
              li: ({ children, ...props }) => (
                <li className="ml-5 list-disc leading-tight mb-1" {...props}>
                  {children}
                </li>
              ),
            }}
          >
            {isWebFallback
              ? "⚠️ No direct Wikipedia match. Try the manual search link below."
              : text}
          </ReactMarkdown>
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

export default ChatMessageBubble;
