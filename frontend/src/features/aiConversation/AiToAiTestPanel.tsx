import React, { useState, useCallback, useMemo } from "react";
import { sendAiToAiMessage } from "../../services/aiApi";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import type { AiToAiResponse } from "../../types/ai";

const AiToAiTestPanel: React.FC = () => {
  const [topic, setTopic] = useState("");
  const [starter, setStarter] = useState<"openai" | "anthropic">("openai");
  const [result, setResult] = useState<AiToAiResponse | null>(null);
  const [loading, setLoading] = useState(false);

  const role = useMemoryStore((state) => state.role);
  const projectId = useProjectStore((state) => state.projectId);

  const roleId = useMemo(() => {
    return typeof role?.id === "number" ? role.id : null;
  }, [role]);

  const isValidProject = useMemo(() => {
    return typeof projectId === "number";
  }, [projectId]);

  const canRun = useMemo(() => {
    return topic.trim().length > 0 && roleId !== null && isValidProject;
  }, [topic, roleId, isValidProject]);

  const handleRun = useCallback(async () => {
    const trimmedTopic = topic.trim();
    if (!trimmedTopic || roleId === null || !isValidProject) {
      console.warn("⛔ Invalid input or missing role/project.");
      return;
    }

    setLoading(true);
    try {
      const response = await sendAiToAiMessage(
        trimmedTopic,
        starter,
        roleId,
        projectId as number
      );
      setResult(response);
    } catch (err) {
      console.error("❌ AI-to-AI error:", err);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [topic, starter, roleId, isValidProject, projectId]);

  return (
    <div className="border rounded-xl p-4 bg-white shadow-md mt-4 max-w-4xl mx-auto">
      <h2 className="text-lg font-semibold mb-3">🧠 AI-to-AI Conversation</h2>

      <div className="flex flex-col sm:flex-row gap-2 sm:items-center mb-4">
        <input
          type="text"
          placeholder="Enter topic (e.g. Mars colonization)"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          className="flex-1 px-3 py-2 border border-gray-300 rounded-md"
        />

        <select
          value={starter}
          onChange={(e) => setStarter(e.target.value as "openai" | "anthropic")}
          className="px-3 py-2 border border-gray-300 rounded-md bg-white"
        >
          <option value="openai">Start with OpenAI</option>
          <option value="anthropic">Start with Claude</option>
        </select>

        <button
          onClick={handleRun}
          disabled={loading || !canRun}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Run"}
        </button>
      </div>

      {result && (
        <div className="bg-gray-50 border rounded-lg p-4 text-sm space-y-4">
          <div>
            <p className="font-semibold mb-1">Conversation:</p>
            <div className="space-y-2">
              {result.messages.map((msg, i) => (
                <div key={msg.id ?? i}>
                  <strong>{msg.sender}:</strong> {msg.text}
                </div>
              ))}
            </div>
          </div>

          {result.messages[2]?.text && (
            <div>
              <p className="font-semibold">🧾 Final Summary:</p>
              <div className="bg-white border rounded p-3 mt-1 text-gray-700">
                {result.messages[2].text}
              </div>
            </div>
          )}

          {Array.isArray(result.youtube) && result.youtube.length > 0 && (
            <div>
              <p className="font-semibold">📺 YouTube Results:</p>
              <ul className="list-disc pl-5 space-y-1 text-blue-700">
                {result.youtube.map((v, i) => (
                  <li key={i}>
                    <a href={v.url} target="_blank" rel="noopener noreferrer">
                      {v.title}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {Array.isArray(result.web) && result.web.length > 0 && (
            <div>
              <p className="font-semibold">🌐 Web Search Results:</p>
              <ul className="list-disc pl-5 space-y-2 text-gray-800">
                {result.web.map((item, i) => (
                  <li key={i}>
                    <a
                      href={item.url}
                      className="text-blue-700"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      {item.title}
                    </a>
                    <p className="text-gray-600 text-xs">{item.snippet}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default AiToAiTestPanel;
