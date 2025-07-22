// src/components/Chat/ChatArea.tsx

import React, { useEffect, useRef } from "react";
import ChatMessageBubble from "./ChatMessageBubble";
import TypingIndicator from "./TypingIndicator";
import SummaryBubble from "./SummaryBublb";
import YouTubeMessages from "./YouTubeMessages";
import WebSearchResults from "./WebSearchResults";
import { useChatStore } from "../../store/chatStore";
import type { ChatMessage } from "../../types/chat";

const ChatArea: React.FC = () => {
  const messages = useChatStore((state) => state.messages);
  const isTyping = useChatStore((state) => state.isTyping);
  const chatBottomRef = useRef<HTMLDivElement | null>(null);

  // 🔍 Debug: detect duplicate keys
  useEffect(() => {
    const idMap = new Map();
    const duplicates: string[] = [];

    messages.forEach((msg) => {
      if (idMap.has(msg.id)) {
        duplicates.push(msg.id);
      } else {
        idMap.set(msg.id, true);
      }
    });

    if (duplicates.length) {
      console.warn("⚠️ Duplicate message IDs detected:", duplicates);
      console.table(messages.filter((m) => duplicates.includes(m.id)));
    }
  }, [messages]);

  // 👇 Auto-scroll
  useEffect(() => {
    const scrollToBottom = () => {
      chatBottomRef.current?.scrollIntoView({ behavior: "smooth" });
    };
    const timeout = setTimeout(scrollToBottom, 50);
    return () => clearTimeout(timeout);
  }, [messages, isTyping]);

  return (
    <div className="flex flex-col gap-4 max-w-4xl mx-auto px-3 sm:px-5 py-4">
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
  );
};

export default ChatArea;
