// File: src/components/Chat/ChatHistoryPanel.tsx
import React, { useState, useMemo } from "react";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import { summarizeChat } from "../../services/aiApi";
import type { ChatMessage } from "../../types/chat";
import { logSessionFlow } from "../../utils/debugSessionFlow";

const ChatHistoryPanel: React.FC = () => {
  const role = useMemoryStore((state) => state.role);
  const roleId = role?.id;
  const projectId = useProjectStore((state) => state.projectId);
  const chatSessionId = useChatStore((state) => state.chatSessionId);
  const messages = useChatStore((state) => state.messages);
  const summaries = useChatStore((state) => state.summaries || []);
  const rotateSession = useChatStore(
    (state) => state.rotateChatSessionAfterSummary
  );

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

  const handleSummarize = async () => {
    if (!roleId || !projectId || !chatSessionId) return;

    try {
      setLoadingSummary(true);
      logSessionFlow("📤 ChatHistoryPanel → Requesting summarization", {
        roleId,
        projectId,
        chatSessionId,
        messagesCount: messages.length,
      });

      const { summary, new_chat_session_id } = await summarizeChat(
        roleId,
        projectId,
        chatSessionId
      );

      logSessionFlow("✅ Summary received", {
        summaryPreview: summary.slice(0, 60),
        new_chat_session_id,
      });

      if (new_chat_session_id) {
        await rotateSession(projectId, roleId, new_chat_session_id);
        logSessionFlow("🔁 Session rotated", { new_chat_session_id });
      }
    } catch (err) {
      console.error("❌ Summarization failed:", err);
      setError("Summarization failed. Please try again.");
    } finally {
      setLoadingSummary(false);
    }
  };

  if (error) {
    return <div className="text-red-500 p-4">{error}</div>;
  }

  return (
    <div className="text-sm text-gray-800 space-y-4 overflow-y-auto h-full pr-2">
      {/* Summaries Section */}
      <div>
        <div className="flex items-center justify-between mb-2">
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
              key={`summary-${s.timestamp || i}`}
              className="p-2 bg-blue-50 rounded"
            >
              {s.summary}
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
                {m.sender}:
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
