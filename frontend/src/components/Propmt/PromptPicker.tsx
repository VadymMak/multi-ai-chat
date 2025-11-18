import React, { useState, useEffect, useMemo, useCallback } from "react";
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
  const [error, setError] = useState<string | null>(null);

  const role = useMemoryStore((s) => s.role);

  const roleId = useMemo(
    () => (typeof role?.id === "number" ? role.id : null),
    [role]
  );

  useEffect(() => {
    if (!roleId) {
      console.warn("❗ No role ID provided – cannot fetch prompts.");
      setTemplates([]);
      return;
    }

    fetchPromptsByRole(roleId)
      .then((res) => {
        console.log("📥 Loaded prompts:", res);
        setTemplates(res || []);
        setError(null);
      })
      .catch((err) => {
        console.error("❌ Failed to load prompt templates:", err);
        setError("Failed to load prompts");
        setTemplates([]);
      });
  }, [roleId]);

  const selectedTemplate = useMemo(
    () => templates.find((t) => t.id === selectedId) || null,
    [selectedId, templates]
  );

  useEffect(() => {
    if (selectedTemplate) {
      setPromptText(selectedTemplate.content);
      setExpanded(true);
    }
  }, [selectedTemplate]);

  const handleUsePrompt = useCallback(() => {
    if (!promptText.trim()) return;

    console.log("🧠 Prompt Generated:", promptText);
    onPromptReady(promptText);
  }, [promptText, onPromptReady]);

  const toggleExpanded = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  return (
    <div className="border border-gray-300 rounded-xl bg-white p-3 shadow-sm">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex-1 w-full">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            🧩 Prompt Templates
          </label>
          <select
            onChange={(e) => setSelectedId(Number(e.target.value))}
            value={selectedId ?? ""}
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
            onClick={toggleExpanded}
            className="text-sm text-blue-600 hover:underline mt-2 sm:mt-0"
          >
            {expanded ? "Hide" : "Show"} Prompt
          </button>
        )}
      </div>

      {error && <div className="text-red-500 text-sm mt-2">{error}</div>}

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
