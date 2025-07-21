import React, { useEffect, useRef } from "react";
import ChatMessageBubble from "./ChatMessageBubble";
import TypingIndicator from "./TypingIndicator";
import { useChatStore } from "../../store/chatStore";

const ChatArea: React.FC = () => {
  const messages = useChatStore((state) => state.messages);
  const isTyping = useChatStore((state) => state.isTyping);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll to bottom when messages or typing state change
  useEffect(() => {
    if (chatBottomRef.current) {
      chatBottomRef.current.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isTyping]);

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto px-2 sm:px-4">
      {messages.map((msg, index) => {
        const isLast = index === messages.length - 1;
        const isAi = msg.sender !== "user";

        return (
          <ChatMessageBubble
            key={msg.id}
            message={msg}
            isLatestAiMessage={isLast && isAi}
          />
        );
      })}

      {isTyping && <TypingIndicator />}

      {/* Auto-scroll anchor */}
      <div ref={chatBottomRef} className="h-4" />
    </div>
  );
};

export default ChatArea;
