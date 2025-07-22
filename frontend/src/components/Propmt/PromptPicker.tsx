import React, { useState, useMemo } from "react";
import { promptTemplates, PromptTemplate } from "../../prompts/promptTemplate";
import { useModelStore } from "../../store/modelStore";
// import { toast } from "react-hot-toast"; // Optional toast

interface PromptPickerProps {
  onPromptReady: (finalPrompt: string) => void;
}

const PromptPicker: React.FC<PromptPickerProps> = ({ onPromptReady }) => {
  const [selected, setSelected] = useState<PromptTemplate | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState(false);

  const provider = useModelStore((state) => state.provider);
  const setProvider = useModelStore((state) => state.setProvider);

  const handleSelect = (id: string) => {
    const template = promptTemplates.find((t) => t.id === id);
    setSelected(template || null);
    setValues(template?.defaultValues || {});
    setExpanded(true);
  };

  const handleChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
  };

  const buildPrompt = useMemo(() => {
    if (!selected) return "";
    let result = selected.template;
    selected.placeholders.forEach((key) => {
      // ✅ Replace all instances of each placeholder
      result = result.replace(
        new RegExp(`\\[${key}\\]`, "g"),
        values[key] || ""
      );
    });
    return result;
  }, [selected, values]);

  const handleUsePrompt = () => {
    if (!buildPrompt.trim()) return;

    // 🔒 Optionally warn if any fields are empty
    const hasEmpty = selected?.placeholders.some((k) => !values[k]?.trim());
    if (hasEmpty) {
      alert("Please fill in all fields before using the prompt.");
      return;
    }

    // 🛡️ Prevent Boost Mode issues
    if (provider === "boost") {
      setProvider("openai");
      // toast("⚠️ Prompt generator not supported in Boost Mode. Switched to OpenAI.");
      console.warn(
        "Prompt used in Boost Mode — switched to OpenAI automatically."
      );
    }

    console.log("🧠 Prompt Generated:", buildPrompt);
    onPromptReady(buildPrompt);
  };

  return (
    <div className="border border-gray-300 rounded-xl bg-white p-3 shadow-sm">
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
        <div className="flex-1">
          <label className="block text-sm font-medium text-gray-700 mb-1">
            🧩 Prompt Tools
          </label>
          <select
            onChange={(e) => handleSelect(e.target.value)}
            defaultValue=""
            className="w-full px-3 py-2 border rounded text-sm"
          >
            <option value="" disabled>
              Select a prompt...
            </option>
            {promptTemplates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} — {t.description}
              </option>
            ))}
          </select>
        </div>

        {selected && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-sm text-blue-600 hover:underline mt-2 sm:mt-0"
          >
            {expanded ? "Hide Details" : "Show Details"}
          </button>
        )}
      </div>

      {expanded && selected && (
        <div className="mt-4 space-y-3">
          {selected.placeholders.map((key) => (
            <div key={key}>
              <label className="text-sm font-medium capitalize">{key}</label>
              <input
                type="text"
                value={values[key] || ""}
                onChange={(e) => handleChange(key, e.target.value)}
                placeholder={`Enter ${key}...`}
                className="w-full px-3 py-1.5 border rounded text-sm"
              />
            </div>
          ))}

          <div className="mt-3">
            <label className="block text-sm font-semibold mb-1 text-gray-700">
              📄 Live Prompt Preview
            </label>
            <pre className="whitespace-pre-wrap bg-gray-100 p-3 rounded text-sm text-gray-800 border border-gray-200 max-h-60 overflow-auto">
              {buildPrompt || "No prompt preview."}
            </pre>
          </div>

          <div className="flex justify-end pt-2">
            <button
              onClick={handleUsePrompt}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
              disabled={!buildPrompt.trim()}
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
