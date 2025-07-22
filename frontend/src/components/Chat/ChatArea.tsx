// src/components/Chat/ChatArea.tsx
import React, {
  useEffect,
  useRef,
  useState,
  useCallback,
  FC,
  useMemo,
  useDeferredValue,
  memo,
  useLayoutEffect,
} from "react";
import ChatMessageBubble from "./ChatMessageBubble";
import TypingIndicator from "./TypingIndicator";
import SummaryBubble from "./SummaryBubble";
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

const ChatAreaBase: FC<ChatAreaProps> = ({ bottomPad = 84 }) => {
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

  const { duringStream, onFinal } = useAutoScroll(containerRef);
  const prevTypingRef = useRef<boolean>(isTyping);

  // Only messages in active context
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

  const messagesToRender = useDeferredValue(filteredMessages);

  const scrollToBottomNow = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    // Snap immediately (no smooth) to guarantee bottom pin
    el.scrollTop = el.scrollHeight;
    chatBottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    chatBottomRef.current?.scrollIntoView({
      behavior: smooth ? "smooth" : "auto",
      block: "end",
    });
  }, []);

  const isUserNearBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return true;
    const { scrollTop, scrollHeight, clientHeight } = el;
    return scrollHeight - scrollTop - clientHeight < 100;
  }, []);

  // Keep pinned during streaming
  useEffect(() => {
    if (isTyping && isUserNearBottom()) {
      duringStream();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isTyping, filteredMessages.length]);

  // Snap at start-of-stream; smooth at end-of-stream
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

  // ✅ Robust initial “jump to bottom” once per session, even on first selection
  const didInitialBottomScroll = useRef<string | null>(null);
  useLayoutEffect(() => {
    if (!sessionReady || !chatSessionId) return;
    if (didInitialBottomScroll.current === chatSessionId) return;
    if (!filteredMessages.length) return;

    didInitialBottomScroll.current = chatSessionId;

    // Try immediately (before paint)…
    scrollToBottomNow();

    // …then again after layout settles (double RAF) to catch late mounts
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        scrollToBottomNow();
      });
    });

    // Final tiny fallback after images/embeds/layout shifts
    const t = window.setTimeout(scrollToBottomNow, 250);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionReady, chatSessionId, filteredMessages.length]);

  // If InputBar height changes and we’re near bottom, keep pinned
  useEffect(() => {
    if (isUserNearBottom()) {
      chatBottomRef.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [bottomPad, isUserNearBottom]);

  // Show/hide "scroll to bottom" button
  useEffect(() => {
    if (!sessionReady) return;

    const root = containerRef.current ?? null;
    const target = chatBottomRef.current ?? null;
    if (!target) return;

    const observer = new IntersectionObserver(
      ([entry]) => setShowScrollButton(!entry.isIntersecting),
      { root, threshold: 0.99 } // slightly stricter threshold = fewer false negatives
    );

    observer.observe(target);
    return () => {
      try {
        observer.unobserve(target);
      } catch {}
      observer.disconnect();
    };
  }, [sessionReady]);

  const scrollBtnBottom = useMemo(
    () => Math.max(24, Math.round(bottomPad) + 12),
    [bottomPad]
  );

  return (
    <div
      ref={containerRef}
      className="relative h-full min-w-0 overflow-y-auto bg-white"
      role="log"
      aria-live="polite"
      aria-busy={isTyping ? "true" : "false"}
      aria-relevant="additions"
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
          messagesToRender.length === 0 &&
          !isTyping && (
            <div className="text-center text-sm text-gray-400 py-12">
              🗃️ No messages in this session yet.
            </div>
          )}

        {sessionReady &&
          messagesToRender.map((msg: ChatMessage, idx) => {
            const key = msg.id || `${msg.sender}-${idx}`;
            const isLast = idx === messagesToRender.length - 1;
            const isAi = msg.sender !== "user";

            const nextMsg = messagesToRender[idx + 1];
            const nextIsDedicatedYt = nextMsg?.sender === "youtube";
            const nextIsDedicatedWeb = nextMsg?.sender === "web";

            // Sidecars on normal assistant messages (hide if a dedicated card follows)
            const hasYtSidecar = Boolean((msg as any).sources?.youtube?.length);
            const hasWebSidecar = Boolean((msg as any).sources?.web?.length);
            const canShowSidecars =
              !msg.isTyping && !(nextIsDedicatedYt || nextIsDedicatedWeb);

            // Dedicated "youtube" message
            if (msg.sender === "youtube") {
              const hasStructured = Boolean(
                (msg as any).sources?.youtube?.length
              );
              return (
                <React.Fragment key={key}>
                  {!msg.isTyping && hasStructured ? (
                    <YouTubeMessages message={msg} />
                  ) : (
                    <ChatMessageBubble
                      message={msg}
                      isLatestAiMessage={isLast && isAi}
                    />
                  )}
                </React.Fragment>
              );
            }

            // Dedicated "web" message
            if (msg.sender === "web") {
              const hasStructured = Boolean((msg as any).sources?.web?.length);
              return (
                <React.Fragment key={key}>
                  {!msg.isTyping && hasStructured ? (
                    <WebSearchResults message={msg} />
                  ) : (
                    <ChatMessageBubble
                      message={msg}
                      isLatestAiMessage={isLast && isAi}
                    />
                  )}
                </React.Fragment>
              );
            }

            // Divider marker
            if (
              (msg.sender === "system" || msg.sender === "final") &&
              (msg.text || "").trim().toLowerCase() === PHASE_MARKER_TEXT
            ) {
              return (
                <React.Fragment key={key}>
                  <Divider text="📌 New Phase Started After Summarization" />
                </React.Fragment>
              );
            }

            // Summary bubble
            if (msg.isSummary) {
              return (
                <React.Fragment key={key}>
                  <SummaryBubble text={msg.text} deferWhileTyping />
                </React.Fragment>
              );
            }

            // Default assistant/user message with optional sidecars
            return (
              <React.Fragment key={key}>
                <ChatMessageBubble
                  message={msg}
                  isLatestAiMessage={isLast && isAi}
                />
                {hasYtSidecar && canShowSidecars && (
                  <YouTubeMessages message={msg} />
                )}
                {hasWebSidecar && canShowSidecars && (
                  <WebSearchResults message={msg} />
                )}
              </React.Fragment>
            );
          })}

        {sessionReady && isTyping && <TypingIndicator />}
        <div ref={chatBottomRef} className="h-4" />
      </div>

      {showScrollButton && (
        <button
          onClick={() => scrollToBottom(true)}
          className="fixed right-4 z-40 p-2 bg-blue-600 text-white rounded-full shadow-lg hover:bg-blue-700 transition"
          style={{ bottom: scrollBtnBottom }}
          aria-label="Scroll to bottom"
          type="button"
        >
          {FiChevronDown({ size: 20 })}
        </button>
      )}
    </div>
  );
};

const propsEqual = (a: ChatAreaProps, b: ChatAreaProps) =>
  (a.bottomPad ?? 84) === (b.bottomPad ?? 84);

export default memo(ChatAreaBase, propsEqual);
