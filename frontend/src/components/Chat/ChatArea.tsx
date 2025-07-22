// File: src/components/Chat/ChatArea.tsx

import React, { useEffect, useRef, useState, useCallback, FC } from "react";
import ChatMessageBubble from "./ChatMessageBubble";
import TypingIndicator from "./TypingIndicator";
import SummaryBubble from "./SummaryBublb";
import YouTubeMessages from "./YouTubeMessages";
import WebSearchResults from "./WebSearchResults";
import { useChatStore } from "../../store/chatStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { ChatMessage } from "../../types/chat";
import { FiChevronDown } from "react-icons/fi";
import { isValidSender } from "../../utils/isValidSender";

const Divider: FC<{ text: string }> = ({ text }) => (
  <div className="flex items-center justify-center my-4">
    <div className="border-t border-gray-300 flex-grow mr-2" />
    <span className="text-xs text-gray-500 font-medium">{text}</span>
    <div className="border-t border-gray-300 flex-grow ml-2" />
  </div>
);

const ChatArea: FC = () => {
  const allMessages = useChatStore((state) => state.messages);
  const isTyping = useChatStore((state) => state.isTyping);
  const role = useMemoryStore((state) => state.role);
  const projectId = useProjectStore((state) => state.projectId);
  const chatSessionId = useChatStore((state) => state.chatSessionId);

  const roleId = role?.id ?? null;

  const messages = allMessages.filter((msg) => {
    if (!msg || typeof msg !== "object") return false;
    if (!isValidSender(msg.sender)) return false;

    const sameProject = String(msg.project_id) === String(projectId);
    const sameRole = String(msg.role_id) === String(roleId);
    const sameSession = msg.chat_session_id === chatSessionId;

    return sameProject && sameRole && sameSession;
  });

  console.log("🧪 Filtered messages for this session:", messages);
  console.log("🗂️ All messages in store:", allMessages);

  const chatBottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const scrollToBottom = useCallback((smooth = true) => {
    chatBottomRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "end",
    });
  }, []);

  const isUserNearBottom = useCallback(() => {
    if (!containerRef.current) return true;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    return scrollHeight - scrollTop - clientHeight < 100;
  }, []);

  useEffect(() => {
    if (isUserNearBottom()) {
      const timeout = setTimeout(() => scrollToBottom(true), 50);
      return () => clearTimeout(timeout);
    }
  }, [messages, isTyping, scrollToBottom, isUserNearBottom]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => setShowScrollButton(!entry.isIntersecting),
      { root: containerRef.current, threshold: 0.98 }
    );

    const el = chatBottomRef.current;
    if (el) observer.observe(el);

    return () => {
      if (el) observer.unobserve(el);
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="relative flex-1 overflow-y-auto pb-20 bg-white"
    >
      <div className="relative flex flex-col gap-4 max-w-4xl mx-auto px-3 sm:px-5 py-4">
        {messages.length === 0 && !isTyping && (
          <div className="text-center text-sm text-gray-400 py-12">
            🗃️ No messages in this session yet.
          </div>
        )}

        {messages.map((msg: ChatMessage, idx: number) => {
          const isLast = idx === messages.length - 1;
          const isAi = msg.sender !== "user";

          if (msg.sender === "youtube") {
            return <YouTubeMessages key={msg.id} message={msg} />;
          }

          if (msg.sender === "web") {
            return <WebSearchResults key={msg.id} message={msg} />;
          }

          if (msg.isSummary) {
            return <SummaryBubble key={msg.id} text={msg.text} />;
          }

          if (
            msg.sender === "system" &&
            msg.text === "📌 New Phase After Summarization"
          ) {
            return (
              <Divider key={msg.id} text="📌 New Phase After Summarization" />
            );
          }

          return (
            <ChatMessageBubble
              key={msg.id}
              message={msg}
              isLatestAiMessage={isLast && isAi}
            />
          );
        })}

        {isTyping && <TypingIndicator />}
        <div ref={chatBottomRef} className="h-4" />
      </div>

      {showScrollButton && (
        <button
          onClick={() => scrollToBottom()}
          className="fixed bottom-24 right-4 z-40 p-2 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition"
          aria-label="Scroll to bottom"
        >
          {FiChevronDown({ size: 20 })}
        </button>
      )}
    </div>
  );
};

export default ChatArea;
