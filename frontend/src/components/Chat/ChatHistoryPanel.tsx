import React, {
  useEffect,
  useState,
  useCallback,
  useMemo,
  useRef,
} from "react";
import { AxiosError } from "axios";
import api from "../../services/api";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";

interface ChatMessage {
  role: string;
  content: string;
  timestamp?: string;
}

interface ChatSummary {
  summary: string;
  timestamp?: string;
}

interface ChatHistoryResponse {
  messages: ChatMessage[];
  summaries: ChatSummary[];
}

const ChatHistoryPanel: React.FC = () => {
  const role = useMemoryStore((state) => state.role);
  const projectId = useProjectStore((state) => state.projectId);
  const roleId = role?.id;

  const [history, setHistory] = useState<ChatHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isReadyToFetch = useMemo(
    () => !!roleId && !!projectId,
    [roleId, projectId]
  );

  const hasFetched = useRef(false);

  const fetchHistory = useCallback(async () => {
    try {
      const res = await api.get<ChatHistoryResponse>("/chat/history", {
        params: {
          role_id: roleId,
          project_id: projectId,
        },
      });
      setHistory(res.data);
    } catch (err) {
      const error = err as AxiosError;
      console.error("❌ Failed to fetch chat history", error.message);
      setError("Failed to load history");
    }
  }, [roleId, projectId]);

  useEffect(() => {
    if (isReadyToFetch && !hasFetched.current) {
      fetchHistory();
      hasFetched.current = true;
    }
  }, [isReadyToFetch, fetchHistory]);

  if (error) {
    return <div className="text-red-500 p-4">{error}</div>;
  }

  if (!history) {
    return <div className="text-sm text-gray-400 p-4">Loading history…</div>;
  }

  return (
    <div className="text-sm text-gray-800 space-y-4 overflow-y-auto h-full pr-2">
      <div>
        <h3 className="text-blue-600 font-semibold mb-2">🧠 Summaries</h3>
        <ul className="space-y-1">
          {history.summaries.map((s, i) => (
            <li key={s.timestamp ?? i} className="p-2 bg-blue-50 rounded">
              {s.summary}
            </li>
          ))}
        </ul>
      </div>

      <div>
        <h3 className="text-green-600 font-semibold mt-6 mb-2">
          💬 Recent Messages
        </h3>
        <ul className="space-y-1">
          {history.messages.map((m, i) => (
            <li key={m.timestamp ?? i} className="p-2 bg-gray-100 rounded">
              <span className="font-semibold text-gray-600 mr-1">
                {m.role}:
              </span>
              {m.content}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default ChatHistoryPanel;
