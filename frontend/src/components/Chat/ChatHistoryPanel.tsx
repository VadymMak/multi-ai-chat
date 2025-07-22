// File: src/components/Chat/ChatHistoryPanel.tsx
import React, { useState, useMemo, useCallback } from "react";
import { v4 as uuidv4 } from "uuid";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import { summarizeChat } from "../../services/aiApi";
import type { ChatMessage } from "../../types/chat";
import { logSessionFlow } from "../../utils/debugSessionFlow";

const ChatHistoryPanel: React.FC = () => {
  const roleId = useMemoryStore((s) =>
    typeof s.role?.id === "number" ? s.role.id : null
  );
  const projectId = useProjectStore((s) => s.projectId ?? null);

  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const messages = useChatStore((s) => s.messages);
  const summaries = useChatStore((s) => s.summaries || []);

  const addMessage = useChatStore((s) => s.addMessage);
  const rotateSession = useChatStore((s) => s.rotateChatSessionAfterSummary);

  const [loadingSummary, setLoadingSummary] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReady = useMemo(() => !!roleId && !!projectId, [roleId, projectId]);
  const hasMessages = useMemo(() => messages.length > 0, [messages]);

  const disableReason = !isReady
    ? "Select a role and project to enable summarization."
    : !chatSessionId
    ? "No active chat session found."
    : !hasMessages
    ? "You need at least one message to summarize."
    : null;

  // Treat "summary/system/final" style as divider-like
  const isDividerLike = useCallback((m: ChatMessage) => {
    if (m.isSummary) return true;
    const s = String((m as any).sender);
    return s === "final" || s === "system";
  }, []);

  const lastIsDivider = useCallback(() => {
    if (!messages.length) return false;
    return isDividerLike(messages[messages.length - 1]);
  }, [messages, isDividerLike]);

  const shouldAppendDivider = useCallback(
    (targetSessionId: string, dividerText?: string) => {
      if (lastIsDivider()) return false;

      const text = (dividerText || "").trim();
      if (!text) return true;

      // Look backwards within this session; if last divider has same text, skip
      for (let i = messages.length - 1; i >= 0; i--) {
        const m = messages[i];
        if (isDividerLike(m) && m.chat_session_id === targetSessionId) {
          if ((m.text || "").trim() === text) return false;
          break;
        }
      }
      return true;
    },
    [messages, lastIsDivider, isDividerLike]
  );

  const handleSummarize = async () => {
    if (!roleId || !projectId || !chatSessionId) return;

    try {
      setError(null);
      setLoadingSummary(true);

      logSessionFlow("📤 ChatHistoryPanel → Requesting summarization", {
        roleId,
        projectId,
        chatSessionId,
        messagesCount: messages.length,
      });

      const resp = await summarizeChat(roleId, projectId, chatSessionId);

      // Backend compatibility
      const divider =
        (resp as any)?.divider_message ?? (resp as any)?.divider ?? null;

      const sessionFromResp = (resp as any)?.chat_session_id as
        | string
        | undefined;
      const newChatSessionId = (resp as any)?.new_chat_session_id as
        | string
        | undefined;

      if (newChatSessionId) {
        // If backend rotates, switch to the new session and seed divider there
        await rotateSession(projectId, roleId, newChatSessionId);

        if (divider) {
          const targetId = newChatSessionId;
          if (shouldAppendDivider(targetId, divider.text)) {
            addMessage({
              id: divider.id || `divider-${uuidv4()}`,
              sender: "system", // avoid TS issues; styling uses isSummary
              text: divider.text || "Summary generated.",
              isTyping: false,
              isSummary: true,
              role_id: divider.role_id ?? roleId,
              project_id: divider.project_id ?? (projectId as any), // accept string/number
              chat_session_id: targetId,
            });
          }
          logSessionFlow("🔁 Session rotated + divider appended", {
            new_chat_session_id: newChatSessionId,
            dividerPreview: divider.text?.slice(0, 60),
          });
        } else {
          logSessionFlow("🔁 Session rotated (no divider provided)", {
            new_chat_session_id: newChatSessionId,
          });
        }
        return;
      }

      // Default: append divider to CURRENT session (or to the session id returned)
      if (divider) {
        const targetId =
          sessionFromResp || divider.chat_session_id || chatSessionId!;
        if (shouldAppendDivider(targetId, divider.text)) {
          addMessage({
            id: divider.id || `divider-${uuidv4()}`,
            sender: "system",
            text: divider.text || "Summary generated.",
            isTyping: false,
            isSummary: true,
            role_id: divider.role_id ?? roleId,
            project_id: divider.project_id ?? (projectId as any), // accept string/number
            chat_session_id: targetId,
          });
        }
        logSessionFlow("✅ Summary divider appended (no rotation)", {
          preview: divider.text?.slice(0, 60),
          chat_session_id: sessionFromResp || chatSessionId,
        });
      } else {
        logSessionFlow("⚠️ No divider returned from summarization", {});
      }
    } catch (err: any) {
      console.error("❌ Summarization failed:", err);
      const detail =
        err?.response?.data?.detail ||
        err?.message ||
        (typeof err?.response?.data === "string"
          ? err.response.data.slice(0, 200)
          : "Unknown error");
      setError(detail || "Summarization failed. Please try again.");
    } finally {
      setLoadingSummary(false);
    }
  };

  if (error) {
    return <div className="text-red-500 p-4">{error}</div>;
  }

  return (
    // NOTE: no overflow/h-full here — parent sidebar owns the scroll
    <div className="text-sm text-gray-800 space-y-4 pr-2">
      {/* Summaries Section */}
      <div>
        {/* Optional sticky inside the panel (sticks within sidebar scroller) */}
        <div
          className="sticky top-0 z-10 -mx-2 px-2 py-2 mb-2
                     bg-gray-50/95 backdrop-blur supports-[backdrop-filter]:bg-gray-50/60
                     border-b border-gray-200 flex items-center justify-between"
        >
          <h3 className="text-blue-600 font-semibold">🧠 Summaries</h3>
          <button
            onClick={handleSummarize}
            disabled={!!disableReason || loadingSummary}
            title={disableReason || ""}
            className={`px-3 py-1 rounded text-white ${
              disableReason
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-blue-600 hover:bg-blue-700"
            }`}
          >
            {loadingSummary ? "Summarizing..." : "Summarize Chat"}
          </button>
        </div>

        {disableReason && !loadingSummary && (
          <p className="text-xs text-gray-500 mb-2">{disableReason}</p>
        )}

        <ul className="space-y-1">
          {summaries.filter(Boolean).map((s, i) => (
            <li
              key={`summary-${(s as any).timestamp || i}`}
              className="p-2 bg-blue-50 rounded"
            >
              {(s as any).summary}
            </li>
          ))}
        </ul>
      </div>

      {/* Recent Messages Section */}
      <div>
        <h3 className="text-green-600 font-semibold mt-6 mb-2">
          💬 Recent Messages
        </h3>
        <ul className="space-y-1">
          {messages.map((m: ChatMessage, i) => (
            <li key={m.id || `msg-${i}`} className="p-2 bg-gray-100 rounded">
              <span className="font-semibold text-gray-600 mr-1">
                {String((m as any).sender)}:
              </span>
              {m.text}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default ChatHistoryPanel;
