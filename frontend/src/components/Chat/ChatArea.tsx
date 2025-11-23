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
import { isValidSender } from "../../utils/isValidSender";

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
    <div className="border-t border-border flex-grow mr-2" />
    <span className="text-xs text-text-secondary font-medium">{text}</span>
    <div className="border-t border-border flex-grow ml-2" />
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
  // ✅ ADD: Offline detection
  const [isOffline, setIsOffline] = useState(!navigator.onLine);

  const containerRef = useRef<HTMLDivElement>(null);
  const chatBottomRef = useRef<HTMLDivElement>(null);

  // ✅ ADD: Offline detection listener
  useEffect(() => {
    const handleOnline = () => setIsOffline(false);
    const handleOffline = () => setIsOffline(true);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  // Only messages in active context
  // Only messages in active context
  const filteredMessages = useMemo(() => {
    if (!sessionReady || !chatSessionId || !roleId || !projectId) {
      return [];
    }

    const filtered = allMessages.filter((msg) => {
      if (!msg || typeof msg !== "object") return false;
      const allowSender =
        Boolean(msg.isSummary) ||
        isValidSender(msg.sender) ||
        msg.sender === "system" ||
        msg.sender === "final";

      const match =
        allowSender &&
        String(msg.project_id) === String(projectId) &&
        String(msg.role_id) === String(roleId) &&
        String(msg.chat_session_id) === String(chatSessionId);

      // console.log("🔍 Message:", {
      //   id: msg.id?.substring(0, 8),
      //   proj: `${msg.project_id}===${projectId}`,
      //   role: `${msg.role_id}===${roleId}`,
      //   session: `${msg.chat_session_id?.substring(
      //     0,
      //     8
      //   )}===${chatSessionId?.substring(0, 8)}`,
      //   match,
      // });

      return match;
    });

    return filtered;
  }, [allMessages, projectId, roleId, chatSessionId, sessionReady]);

  // const messagesToRender = useDeferredValue(filteredMessages);
  const messagesToRender = filteredMessages;
  // console.log(
  //   "🎨 [ChatArea] messagesToRender:",
  //   messagesToRender.length,
  //   messagesToRender
  // );

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

  // ✅ Robust initial "jump to bottom" once per session, even on first selection
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

  // ✅ УНИВЕРСАЛЬНЫЙ AUTO-SCROLL
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !sessionReady) return;

    const { scrollTop, scrollHeight, clientHeight } = el;
    const distanceFromBottom = scrollHeight - scrollTop - clientHeight;

    // Скроллить если близко к низу (< 400px)
    if (distanceFromBottom < 400) {
      // Небольшая задержка для обновления DOM
      const timer = setTimeout(() => {
        el.scrollTop = el.scrollHeight;
      }, 10);
      return () => clearTimeout(timer);
    }
  }, [filteredMessages, isTyping, bottomPad, sessionReady]);

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

  return (
    <div
      ref={containerRef}
      className="relative h-full min-w-0 overflow-y-auto bg-background pt-6"
      role="log"
      aria-live="polite"
      aria-busy={isTyping ? "true" : "false"}
      aria-relevant="additions"
      style={{
        scrollbarGutter: "stable" as any,
      }}
    >
      {/* ✅ ADD: Offline banner */}
      {isOffline && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-error text-white px-4 py-2 text-center text-sm font-medium shadow-lg">
          📡 You appear to be offline. Reconnecting...
        </div>
      )}

      <div
        className="relative flex flex-col gap-8 w-full px-4 pt-8"
        style={{ paddingBottom: `${bottomPad + 20}px` }}
      >
        {/* Optional Chat Header */}
        {sessionReady && role && (
          <div className="mb-2 pb-3 border-b border-border/50">
            <p className="text-sm text-text-secondary">
              💬 Chat with{" "}
              <span className="font-medium text-text-primary">{role.name}</span>
            </p>
          </div>
        )}

        {!sessionReady && (
          <div className="text-center text-sm text-text-secondary py-6 animate-pulse">
            ⏳ Initializing session…
          </div>
        )}

        {sessionReady && noHistory && (
          <div className="text-center text-sm text-error py-6">
            📭 No conversation history found for this session.
          </div>
        )}

        {sessionReady &&
          !noHistory &&
          messagesToRender.length === 0 &&
          !isTyping && (
            <div className="text-center text-sm text-text-secondary py-12">
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

        {sessionReady && isTyping && (
          <div className="relative h-0">
            <div className="absolute bottom-0 left-0">
              <TypingIndicator />
            </div>
          </div>
        )}
        <div ref={chatBottomRef} className="h-8" />
      </div>

      {showScrollButton && (
        <button
          onClick={() => scrollToBottom(true)}
          className="fixed z-40 p-3 bg-primary text-text-primary rounded-full shadow-lg hover:opacity-90 transition border border-border"
          style={{
            bottom: "140px", // ← ИЗМЕНИЛИ
            left: "calc(50% + 144px)",
          }}
          aria-label="Scroll to bottom"
          type="button"
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
          >
            <polyline points="6 9 12 15 18 9" />
          </svg>
        </button>
      )}
    </div>
  );
};

const propsEqual = (a: ChatAreaProps, b: ChatAreaProps) =>
  (a.bottomPad ?? 84) === (b.bottomPad ?? 84);

export default memo(ChatAreaBase, propsEqual);
