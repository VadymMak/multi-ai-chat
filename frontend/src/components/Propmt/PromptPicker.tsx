// File: src/components/Prompt/PromptPicker.tsx

import React, { useState, useEffect, useMemo } from "react";
import { useModelStore } from "../../store/modelStore";
import { useMemoryStore } from "../../store/memoryStore";
import { fetchPromptsByRole } from "../../services/aiApi";

interface PromptTemplate {
  id: number;
  role_id: number;
  name: string;
  content: string;
  is_default?: boolean;
}

interface PromptPickerProps {
  onPromptReady: (finalPrompt: string) => void;
}

const PromptPicker: React.FC<PromptPickerProps> = ({ onPromptReady }) => {
  const [templates, setTemplates] = useState<PromptTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [promptText, setPromptText] = useState("");
  const [expanded, setExpanded] = useState(false);

  const role = useMemoryStore((s) => s.role);
  const provider = useModelStore((s) => s.provider);
  const setProvider = useModelStore((s) => s.setProvider);

  const roleId = useMemo(() => {
    return typeof role?.id === "number" ? role.id : null;
  }, [role]);

  useEffect(() => {
    if (!roleId) {
      console.warn("❗ No role ID provided – cannot fetch prompts.");
      return;
    }

    fetchPromptsByRole(roleId)
      .then((res) => {
        console.log("📥 Loaded prompts:", res);
        setTemplates(res || []);
      })
      .catch((err) => {
        console.error("❌ Failed to load prompt templates:", err);
        setTemplates([]);
      });
  }, [roleId]);

  const selectedTemplate = useMemo(() => {
    return templates.find((t) => t.id === selectedId) || null;
  }, [selectedId, templates]);

  useEffect(() => {
    if (selectedTemplate) {
      setPromptText(selectedTemplate.content);
      setExpanded(true);
    }
  }, [selectedTemplate]);

  const handleUsePrompt = () => {
    if (!promptText.trim()) return;

    // Ensure prompt-compatible model is selected
    if (provider === "grok") {
      setProvider("openai");
      console.warn(
        "⚠️ Grok doesn't support prompt injection – switched to OpenAI."
      );
    }

    console.log("🧠 Prompt Generated:", promptText);
    onPromptReady(promptText);
  };

  return (
    <div className="border border-gray-300 rounded-xl bg-white p-3 shadow-sm">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            🧩 Prompt Templates
          </label>
          <select
            onChange={(e) => setSelectedId(Number(e.target.value))}
            defaultValue=""
            className="w-full px-3 py-2 border rounded text-sm"
          >
            <option value="" disabled>
              Select a prompt...
            </option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </div>

        {selectedTemplate && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-sm text-blue-600 hover:underline mt-2 sm:mt-0"
          >
            {expanded ? "Hide" : "Show"} Prompt
          </button>
        )}
      </div>

      {expanded && selectedTemplate && (
        <div className="mt-4 space-y-3">
          <div>
            <label className="block text-sm font-semibold mb-1 text-gray-700">
              📄 Prompt Preview
            </label>
            <textarea
              value={promptText}
              onChange={(e) => setPromptText(e.target.value)}
              className="w-full px-3 py-2 border rounded text-sm bg-gray-100"
              rows={6}
            />
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleUsePrompt}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
              disabled={!promptText.trim()}
            >
              Use This Prompt
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default PromptPicker;
