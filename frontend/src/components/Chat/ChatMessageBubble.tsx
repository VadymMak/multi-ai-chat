import React from "react";
import { motion } from "framer-motion";
import ReactMarkdown from "react-markdown";
import { ChatMessage } from "../../types/chat";
import { getModelIcon } from "../../utils/getModelIcons";

interface Props {
  message: ChatMessage;
  isLatestAiMessage?: boolean; // ✅ allow for typing effects, optional
}

const ChatMessageBubble: React.FC<Props> = ({ message, isLatestAiMessage }) => {
  const isUser = message.sender === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25 }}
      className={`flex w-full ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`relative px-4 py-3 rounded-2xl shadow-md max-w-[85%] sm:max-w-[70%] break-words ${
          isUser
            ? "bg-blue-600 text-white rounded-br-sm"
            : message.isSummary
            ? "bg-blue-50 border border-blue-300 text-blue-900 rounded-bl-sm"
            : "bg-gray-100 text-gray-900 rounded-bl-sm"
        }`}
      >
        {/* AI sender info */}
        {!isUser && (
          <div className="flex items-center gap-2 mb-1 text-sm text-gray-500">
            {getModelIcon(message.sender)}
            <span className="capitalize">
              {message.isSummary ? "📘 Final Summary" : message.sender}
            </span>
          </div>
        )}

        {/* Markdown-rendered content */}
        <ReactMarkdown
          components={{
            p: ({ node, ...props }) => (
              <p
                className="prose prose-sm sm:prose-base break-words max-w-full"
                {...props}
              />
            ),
            a: ({ node, children, ...props }) => (
              <a
                className="text-blue-200 underline hover:text-white"
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
          }}
        >
          {message.text}
        </ReactMarkdown>

        {/* Optional Typing indicator */}
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
