import React, { useState } from "react";
import { sendAiToAiMessage } from "../../services/aiApi";

const AiToAiTestPanel: React.FC = () => {
  const [topic, setTopic] = useState("");
  const [starter, setStarter] = useState<"openai" | "anthropic">("openai");
  const [result, setResult] = useState<any | null>(null);
  const [loading, setLoading] = useState(false);

  const handleRun = async () => {
    if (!topic.trim()) return;
    setLoading(true);
    try {
      const response = await sendAiToAiMessage(topic, starter);
      setResult(response);
    } catch (err) {
      console.error("AI-to-AI error:", err);
      setResult(null);
    } finally {
      setLoading(false);
    }
  };

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
          disabled={loading}
          className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "Thinking..." : "Run"}
        </button>
      </div>

      {result && (
        <div className="bg-gray-50 border rounded-lg p-4 text-sm space-y-3">
          <div>
            <p className="font-semibold mb-1">Conversation:</p>
            <div className="space-y-2">
              {result.conversation.map((msg: any, i: number) => (
                <div key={i}>
                  <strong>{msg.role}:</strong> {msg.content}
                </div>
              ))}
            </div>
          </div>

          <div>
            <p className="font-semibold">🧾 Final Summary:</p>
            <div className="bg-white border rounded p-3 mt-1 text-gray-700">
              {result.final_summary}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AiToAiTestPanel;
