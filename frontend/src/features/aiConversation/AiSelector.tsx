import React, { useMemo, useCallback } from "react";
import { useModelStore } from "../../store/modelStore";
import { getModelIcon } from "../../utils/getModelIcons";
import { FiZap } from "react-icons/fi"; // Boost Mode icon

const AiSelector: React.FC = () => {
  const current = useModelStore((state) => state.provider);
  const setProvider = useModelStore((state) => state.setProvider);

  const models = useMemo(
    () =>
      [
        { id: "openai", label: "OpenAI" },
        { id: "anthropic", label: "Claude" },
        { id: "grok", label: "Grok" },
        { id: "boost", label: "Boost Mode" },
      ] as const, // ✅ fixes TypeScript narrowing
    []
  );

  const handleSelect = useCallback(
    (id: (typeof models)[number]["id"]) => {
      setProvider(id);
    },
    [setProvider] // ✅ removed models
  );

  return (
    <div className="flex flex-wrap gap-2 bg-white border border-gray-200 p-3 rounded-xl shadow-sm">
      {models.map((model) => (
        <button
          key={model.id}
          onClick={() => handleSelect(model.id)}
          className={`flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium border transition 
            ${
              current === model.id
                ? "bg-blue-600 text-white border-blue-600 ring-2 ring-blue-300"
                : "bg-white text-gray-700 border-gray-300 hover:bg-gray-50"
            }`}
        >
          {model.id === "boost"
            ? (FiZap({
                size: 16,
                className: "text-yellow-400",
              }) as React.ReactElement)
            : getModelIcon(model.id)}

          <span>{model.label}</span>
        </button>
      ))}
    </div>
  );
};

export default AiSelector;
