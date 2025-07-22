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
// NOTE: if your file on disk is `SummaryBublb.tsx`, please rename it to `SummaryBubble.tsx`.
import SummaryBubble from "./SummaryBublb";
import YouTubeMessages from "./YouTubeMessages";
import WebSearchResults from "./WebSearchResults";
import { useChatStore } from "../../store/chatStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import type { ChatMessage as BaseChatMessage } from "../../types/chat";
import { FiChevronDown } from "react-icons/fi";
import { isValidSender } from "../../utils/isValidSender";
import { useAutoScroll } from "../../hooks/useAutoScroll";

interface ChatMessage extends BaseChatMessage {
  timestamp?: string;
}

interface ChatAreaProps {
  /** Dynamic bottom padding in px so bubbles don’t sit under the InputBar */
  bottomPad?: number;
}

const PHASE_MARKER_TEXT =
  "📌 new phase started after summarization".toLowerCase();

const Divider: FC<{ text: string }> = ({ text }) => (
  <div className="flex items-center justify-center my-4">
    <div className="border-t border-gray-300 flex-grow mr-2" />
    <span className="text-xs text-gray-500 font-medium">{text}</span>
    <div className="border-t border-gray-300 flex-grow ml-2" />
  </div>
);

const ChatArea: FC<ChatAreaProps> = ({ bottomPad = 84 }) => {
  const allMessages = useChatStore((s) => s.messages);
  const isTyping = useChatStore((s) => s.isTyping);
  const noHistory = useChatStore((s) => s.noHistory);
  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const sessionReady = useChatStore((s) => s.sessionReady);

  const role = useMemoryStore((s) => s.role);
  const roleId = role?.id ?? null;
  const projectId = useProjectStore((s) => s.projectId);

  const [showScrollButton, setShowScrollButton] = useState(false);

  const containerRef = useRef<HTMLDivElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<HTMLDivElement>(null); // anchor for LAST user prompt

  // Auto-scroll helpers (RAF during stream, smooth on final)
  const { duringStream, onFinal } = useAutoScroll(containerRef);
  const prevTypingRef = useRef<boolean>(isTyping);

  // Only messages in the active context
  const filteredMessages = useMemo(() => {
    if (!sessionReady || !chatSessionId || !roleId || !projectId) return [];
    return allMessages.filter((msg) => {
      if (!msg || typeof msg !== "object") return false;
      const allowSender =
        Boolean(msg.isSummary) ||
        isValidSender(msg.sender) ||
        msg.sender === "system" ||
        msg.sender === "final";
      return (
        allowSender &&
        String(msg.project_id) === String(projectId) &&
        String(msg.role_id) === String(roleId) &&
        String(msg.chat_session_id) === String(chatSessionId)
      );
    });
  }, [allMessages, projectId, roleId, chatSessionId, sessionReady]);

  // Find the index of the LAST user prompt
  const lastUserIndex = useMemo(() => {
    for (let i = filteredMessages.length - 1; i >= 0; i--) {
      if (filteredMessages[i].sender === "user") return i;
    }
    return -1;
  }, [filteredMessages]);

  // Fallback: first message of last ~20, or after the latest phase divider
  const phaseStartFallbackIndex = useMemo(() => {
    for (let i = filteredMessages.length - 1; i >= 0; i--) {
      const m = filteredMessages[i];
      if (
        (m.sender === "system" || m.sender === "final") &&
        (m.text || "").trim().toLowerCase() === PHASE_MARKER_TEXT
      ) {
        return Math.min(i + 1, filteredMessages.length - 1);
      }
    }
    return Math.max(0, filteredMessages.length - 20);
  }, [filteredMessages]);

  const anchorIndex =
    lastUserIndex >= 0 ? lastUserIndex : phaseStartFallbackIndex;

  const scrollToBottom = useCallback((smooth = true) => {
    chatBottomRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "end",
    });
  }, []);

  const scrollToAnchorTop = useCallback((smooth = false) => {
    anchorRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "start",
    });
  }, []);

  const isUserNearBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return true;
    const { scrollTop, scrollHeight, clientHeight } = el;
    return scrollHeight - scrollTop - clientHeight < 100;
  }, []);

  // Keep pinned during streaming (only if user is near bottom)
  useEffect(() => {
    if (isTyping && isUserNearBottom()) {
      duringStream();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTyping, filteredMessages.length]);

  // Start-of-stream snap + end-of-stream smooth
  useEffect(() => {
    if (!prevTypingRef.current && isTyping) {
      if (isUserNearBottom()) {
        chatBottomRef.current?.scrollIntoView({
          behavior: "auto",
          block: "end",
        });
      }
    }
    if (prevTypingRef.current && !isTyping && isUserNearBottom()) {
      onFinal();
    }
    prevTypingRef.current = isTyping;
  }, [isTyping, onFinal, isUserNearBottom]);

  // One-time jump to the LAST user prompt when a session (or history) loads
  const initialJumpDoneFor = useRef<string | number | null>(null);
  useEffect(() => {
    if (!sessionReady || !chatSessionId) return;
    if (initialJumpDoneFor.current === chatSessionId) return;

    initialJumpDoneFor.current = chatSessionId;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollToAnchorTop(false);
      });
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionReady, chatSessionId, filteredMessages.length]);

  // After each NEW user message, jump it to the top
  const lastAnchoredIdRef = useRef<string | null>(null);
  useEffect(() => {
    const msg = filteredMessages[anchorIndex];
    if (!msg) return;

    const lastMsg = filteredMessages[filteredMessages.length - 1];
    const isNewestUser = lastMsg?.id === msg.id && lastMsg?.sender === "user";

    if (isNewestUser && msg.id !== lastAnchoredIdRef.current) {
      lastAnchoredIdRef.current = msg.id;
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          scrollToAnchorTop(false);
        });
      });
    }
  }, [filteredMessages, anchorIndex, scrollToAnchorTop]);

  // If InputBar height changes and we’re near bottom, keep pinned
  useEffect(() => {
    if (isUserNearBottom()) {
      chatBottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [bottomPad, isUserNearBottom]);

  // Show/hide the scroll-to-bottom button (rebinds if refs change)
  // Re-init the IntersectionObserver when the session becomes ready.
  // We intentionally do not depend on `.current` values.
  // Re-init the IntersectionObserver when the session is ready.
  // Intentionally do NOT depend on `.current` values.
  useEffect(() => {
    if (!sessionReady) return;

    const root = containerRef.current ?? null;
    const target = chatBottomRef.current ?? null;
    if (!target) return;

    const observer = new IntersectionObserver(
      ([entry]) => setShowScrollButton(!entry.isIntersecting),
      { root, threshold: 0.98 }
    );

    observer.observe(target);
    return () => {
      try {
        observer.unobserve(target);
      } catch {}
      observer.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionReady]);

  const scrollBtnBottom = Math.max(24, Math.round(bottomPad) + 12);

  return (
    <div
      ref={containerRef}
      className="relative h-full min-w-0 overflow-y-auto bg-white"
      role="log"
      aria-live="polite"
      aria-busy={isTyping ? "true" : "false"}
      style={{ paddingBottom: bottomPad, scrollbarGutter: "stable" as any }}
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
            const anchorHere = idx === anchorIndex;

            if (msg.sender === "youtube")
              return (
                <React.Fragment key={key}>
                  {anchorHere && <div ref={anchorRef} />}
                  <YouTubeMessages message={msg} />
                </React.Fragment>
              );

            if (msg.sender === "web")
              return (
                <React.Fragment key={key}>
                  {anchorHere && <div ref={anchorRef} />}
                  <WebSearchResults message={msg} />
                </React.Fragment>
              );

            // Divider marker
            if (
              (msg.sender === "system" || msg.sender === "final") &&
              (msg.text || "").trim().toLowerCase() === PHASE_MARKER_TEXT
            ) {
              return (
                <React.Fragment key={key}>
                  {anchorHere && <div ref={anchorRef} />}
                  <Divider text="📌 New Phase Started After Summarization" />
                </React.Fragment>
              );
            }

            if (msg.isSummary) {
              return (
                <React.Fragment key={key}>
                  {anchorHere && <div ref={anchorRef} />}
                  <SummaryBubble text={msg.text} />
                </React.Fragment>
              );
            }

            return (
              <React.Fragment key={key}>
                {anchorHere && <div ref={anchorRef} />}
                <ChatMessageBubble
                  message={msg}
                  isLatestAiMessage={isLast && isAi}
                />
              </React.Fragment>
            );
          })}

        {sessionReady && isTyping && <TypingIndicator />}
        <div ref={chatBottomRef} className="h-4" />
      </div>

      {showScrollButton && (
        <button
          onClick={() => scrollToBottom()}
          className="fixed right-4 z-40 p-2 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition"
          style={{ bottom: scrollBtnBottom }}
          aria-label="Scroll to bottom"
        >
          {FiChevronDown({ size: 20 })}
        </button>
      )}
    </div>
  );
};

export default ChatArea;
