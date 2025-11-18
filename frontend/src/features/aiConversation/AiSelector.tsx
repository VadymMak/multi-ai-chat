// File: src/features/aiConversation/AiSelector.tsx

import React, {
  useMemo,
  useCallback,
  useState,
  useRef,
  useEffect,
} from "react";
import { useModelStore } from "../../store/modelStore";
import { useChatStore } from "../../store/chatStore";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaHandshake, FaChevronDown, FaCheck } from "react-icons/fa";

const HandshakeIcon = FaHandshake as React.ComponentType<{
  size?: number;
  className?: string;
}>;

const ChevronDownIcon = FaChevronDown as React.ComponentType<{
  size?: number;
  className?: string;
}>;

const CheckIcon = FaCheck as React.ComponentType<{
  size?: number;
  className?: string;
}>;

const AiSelector: React.FC = () => {
  const current = useModelStore((state) => state.provider);
  const setProvider = useModelStore((state) => state.setProvider);
  const claudeModel = useChatStore((state) => state.claudeModel);
  const setClaudeModel = useChatStore((state) => state.setClaudeModel);

  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const models = useMemo(
    () =>
      [
        { id: "openai", label: "OpenAI" },
        { id: "anthropic", label: "Claude" },
        { id: "boost", label: "Debate Mode" },
      ] as const,
    []
  );

  const handleSelect = useCallback(
    (id: (typeof models)[number]["id"]) => {
      setProvider(id);
      if (id === "anthropic") {
        setShowModelDropdown(true);
      } else {
        setShowModelDropdown(false);
      }
    },
    [setProvider]
  );

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(event.target as Node)
      ) {
        setShowModelDropdown(false);
      }
    };

    if (showModelDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [showModelDropdown]);

  return (
    <div className="flex flex-row gap-2 flex-wrap">
      {models.map((model) => {
        const isActive = current === model.id;

        // Define color schemes for each model
        let buttonClasses = "";

        if (model.id === "openai") {
          buttonClasses = isActive
            ? "bg-primary text-white shadow-lg shadow-primary/20"
            : "bg-surface text-primary border border-primary hover:bg-primary/10";
        } else if (model.id === "anthropic") {
          buttonClasses = isActive
            ? "bg-success text-background shadow-lg shadow-success/20"
            : "bg-surface text-success border border-success hover:bg-success/10";
        } else if (model.id === "boost") {
          buttonClasses = isActive
            ? "bg-gradient-to-r from-error to-warning text-white shadow-lg"
            : "bg-surface text-error border border-error hover:bg-error/10";
        }

        // Special handling for Claude with dropdown
        if (model.id === "anthropic") {
          return (
            <div key={model.id} className="relative" ref={dropdownRef}>
              <button
                onClick={() => handleSelect(model.id)}
                className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-all duration-200 cursor-pointer hover:scale-105 justify-center ${buttonClasses}`}
              >
                {getModelIcon(model.id)}
                <span>{model.label}</span>
                <ChevronDownIcon size={12} />
              </button>

              {/* Dropdown menu */}
              {isActive && showModelDropdown && (
                <div className="absolute top-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl py-1 z-50 min-w-[220px]">
                  <button
                    onClick={() => {
                      setClaudeModel("claude-sonnet-4-20250514");
                      setShowModelDropdown(false);
                    }}
                    className={`w-full px-4 py-2 text-left hover:bg-gray-700 transition-colors ${
                      claudeModel === "claude-sonnet-4-20250514"
                        ? "bg-gray-700"
                        : ""
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base">⚡</span>
                          <span className="font-medium text-white">
                            Sonnet 4
                          </span>
                        </div>
                        <span className="text-xs text-gray-400 ml-6">
                          Fast & Efficient
                        </span>
                      </div>
                      {claudeModel === "claude-sonnet-4-20250514" && (
                        <CheckIcon size={14} className="text-green-500" />
                      )}
                    </div>
                  </button>

                  <button
                    onClick={() => {
                      setClaudeModel("claude-opus-4-20250514");
                      setShowModelDropdown(false);
                    }}
                    className={`w-full px-4 py-2 text-left hover:bg-gray-700 transition-colors ${
                      claudeModel === "claude-opus-4-20250514"
                        ? "bg-gray-700"
                        : ""
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-base">🌟</span>
                          <span className="font-medium text-white">Opus 4</span>
                        </div>
                        <span className="text-xs text-gray-400 ml-6">
                          Best Quality (5x cost)
                        </span>
                      </div>
                      {claudeModel === "claude-opus-4-20250514" && (
                        <CheckIcon size={14} className="text-green-500" />
                      )}
                    </div>
                  </button>
                </div>
              )}
            </div>
          );
        }

        return (
          <button
            key={model.id}
            onClick={() => handleSelect(model.id)}
            className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-all duration-200 cursor-pointer hover:scale-105 justify-center ${buttonClasses}`}
          >
            {model.id === "boost" ? (
              <HandshakeIcon size={16} />
            ) : (
              getModelIcon(model.id)
            )}
            <span>{model.label}</span>
          </button>
        );
      })}
    </div>
  );
};

export default AiSelector;
