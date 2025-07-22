// File: src/components/Chat/ChatArea.tsx

import React, {
  useEffect,
  useRef,
  useState,
  useCallback,
  FC,
  useMemo,
} from "react";
import ChatMessageBubble from "./ChatMessageBubble";
import TypingIndicator from "./TypingIndicator";
import SummaryBubble from "./SummaryBublb";
import YouTubeMessages from "./YouTubeMessages";
import WebSearchResults from "./WebSearchResults";
import { useChatStore } from "../../store/chatStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import type { ChatMessage as BaseChatMessage } from "../../types/chat";
import { FiChevronDown } from "react-icons/fi";
import { isValidSender } from "../../utils/isValidSender";

interface ChatMessage extends BaseChatMessage {
  timestamp?: string;
}

const Divider: FC<{ text: string }> = ({ text }) => (
  <div className="flex items-center justify-center my-4">
    <div className="border-t border-gray-300 flex-grow mr-2" />
    <span className="text-xs text-gray-500 font-medium">{text}</span>
    <div className="border-t border-gray-300 flex-grow ml-2" />
  </div>
);

const ChatArea: FC = () => {
  const allMessages = useChatStore((s) => s.messages);
  const isTyping = useChatStore((s) => s.isTyping);
  const noHistory = useChatStore((s) => s.noHistory);
  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const isSessionSynced = useChatStore((s) => s.isSessionSynced);

  const role = useMemoryStore((s) => s.role);
  const roleId = role?.id ?? null;
  const projectId = useProjectStore((s) => s.projectId);

  const sessionReady = isSessionSynced();
  const [showScrollButton, setShowScrollButton] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  const filteredMessages = useMemo(() => {
    if (!chatSessionId || !roleId || !projectId) return [];
    return allMessages.filter((msg) => {
      if (!msg || typeof msg !== "object") return false;
      const validSender = isValidSender(msg.sender) || msg.sender === "system";
      return (
        validSender &&
        String(msg.project_id) === String(projectId) &&
        String(msg.role_id) === String(roleId) &&
        String(msg.chat_session_id) === String(chatSessionId)
      );
    });
  }, [allMessages, projectId, roleId, chatSessionId]);

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
  }, [filteredMessages.length, isTyping, scrollToBottom, isUserNearBottom]);

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
      className="relative flex-1 min-w-0 overflow-y-auto pb-20 bg-white"
    >
      <div className="relative flex flex-col gap-4 w-full px-3 sm:px-5 py-4">
        {!sessionReady && (
          <div className="text-center text-sm text-gray-500 py-6 animate-pulse">
            ⏳ Initializing session…
          </div>
        )}

        {sessionReady && noHistory && (
          <div className="text-center text-sm text-red-500 py-6">
            📭 No conversation history found for this session.
          </div>
        )}

        {sessionReady &&
          !noHistory &&
          filteredMessages.length === 0 &&
          !isTyping && (
            <div className="text-center text-sm text-gray-400 py-12">
              🗃️ No messages in this session yet.
            </div>
          )}

        {sessionReady &&
          filteredMessages.map((msg: ChatMessage, idx) => {
            const key = msg.id || `${msg.sender}-${idx}`;
            const isLast = idx === filteredMessages.length - 1;
            const isAi = msg.sender !== "user";

            if (msg.sender === "youtube")
              return <YouTubeMessages key={key} message={msg} />;
            if (msg.sender === "web")
              return <WebSearchResults key={key} message={msg} />;
            if (msg.isSummary)
              return <SummaryBubble key={key} text={msg.text} />;
            if (
              msg.sender === "system" &&
              msg.text?.trim().toLowerCase() ===
                "📌 new phase started after summarization".toLowerCase()
            ) {
              return (
                <Divider
                  key={key}
                  text="📌 New Phase Started After Summarization"
                />
              );
            }

            return (
              <ChatMessageBubble
                key={key}
                message={msg}
                isLatestAiMessage={isLast && isAi}
              />
            );
          })}

        {sessionReady && isTyping && <TypingIndicator />}
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
