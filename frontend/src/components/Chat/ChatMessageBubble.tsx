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

const ChatMessageBubble: React.FC<Props> = ({ message, isLatestAiMessage }) => {
  const isUser = message.sender === "user";
  const isYouTube = message.sender === "youtube";
  const isWeb = message.sender === "web";
  const isSummary = message.isSummary;
  const isOpenAI = message.sender === "openai" && !isSummary;
  const isClaude = message.sender === "anthropic" && !isSummary;

  const isYouTubeFallback =
    isYouTube && message.text.includes("No specific results found");

  const isWebFallback =
    isWeb && message.text.includes("No specific Wikipedia results found");

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`relative px-4 py-3 rounded-2xl max-w-[85%] sm:max-w-[70%] break-words
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
        {/* Sender Badge */}
        {!isUser && !isYouTubeFallback && (
          <div className="flex items-center gap-2 mb-1 text-sm text-gray-500">
            {isYouTube && (
              <>
                {FaYoutube({ className: "text-red-500", size: 16 })}
                <span>📺 YouTube Insight</span>
              </>
            )}
            {isWeb && (
              <>
                {FaGlobeEurope({ className: "text-green-600", size: 16 })}
                <span>🌐 Web Insight</span>
              </>
            )}
            {isSummary && (
              <>
                {getModelIcon("anthropic")}
                <span className="font-serif italic text-[17px] text-violet-800">
                  ✅ Final Answer by <strong>Claude</strong>
                </span>
              </>
            )}
            {isOpenAI && (
              <>
                {getModelIcon("openai")}
                <span className="text-blue-700 font-medium">💡 OpenAI</span>
              </>
            )}
            {isClaude && (
              <>
                {getModelIcon("anthropic")}
                <span className="text-violet-700 font-medium">🤖 Claude</span>
              </>
            )}
          </div>
        )}

        {/* Message Body */}
        <div
          className={`prose max-w-full break-words ${
            isSummary
              ? "prose-violet text-[15.5px] font-serif leading-relaxed"
              : "prose-sm sm:prose-base"
          }`}
        >
          <ReactMarkdown
            components={{
              p: ({ node, ...props }) => (
                <p
                  className={`break-words max-w-full ${
                    isSummary ? "text-violet-900" : ""
                  }`}
                  {...props}
                />
              ),
              a: ({ node, children, ...props }) => (
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
              code: ({ node, ...props }) => (
                <code
                  className="bg-gray-200 px-1 py-0.5 rounded text-xs"
                  {...props}
                />
              ),
              li: ({ node, children, ...props }) => (
                <li className="ml-4 list-disc" {...props}>
                  {children}
                </li>
              ),
            }}
          >
            {isWebFallback
              ? `⚠️ No direct Wikipedia match. Try the manual search link below.`
              : message.text}
          </ReactMarkdown>
        </div>

        {/* Typing Indicator */}
        {message.isTyping && (
          <div className="mt-1 animate-pulse text-sm text-gray-400">
            Typing...
          </div>
        )}
      </div>
    </motion.div>
  );
};

export default ChatMessageBubble;
