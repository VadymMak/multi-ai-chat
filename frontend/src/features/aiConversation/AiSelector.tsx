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
import { useBalanceStore } from "../../store/balanceStore";
import { getModelIcon } from "../../utils/getModelIcons";
import { FaHandshake, FaChevronDown, FaCheck, FaLock } from "react-icons/fa";

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

const LockIcon = FaLock as React.ComponentType<{
  size?: number;
  className?: string;
}>;

const AiSelector: React.FC = () => {
  const current = useModelStore((state) => state.provider);
  const setProvider = useModelStore((state) => state.setProvider);
  const claudeModel = useChatStore((state) => state.claudeModel);
  const setClaudeModel = useChatStore((state) => state.setClaudeModel);

  // Get balance/availability info
  const openaiInfo = useBalanceStore((state) => state.openai);
  const claudeInfo = useBalanceStore((state) => state.claude);

  const [showModelDropdown, setShowModelDropdown] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Check availability
  const isOpenAIAvailable = openaiInfo.available;
  const isClaudeAvailable = claudeInfo.available;
  const isDebateModeAvailable = isOpenAIAvailable && isClaudeAvailable;

  // Get tooltip message for unavailable AI
  const getUnavailableReason = (provider: string): string => {
    if (provider === "openai" && !isOpenAIAvailable) {
      return openaiInfo.error || "OpenAI API key not configured or no credits";
    }
    if (provider === "anthropic" && !isClaudeAvailable) {
      return claudeInfo.error || "Claude API key not configured or no credits";
    }
    if (provider === "boost" && !isDebateModeAvailable) {
      const reasons: string[] = [];
      if (!isOpenAIAvailable) reasons.push("OpenAI unavailable");
      if (!isClaudeAvailable) reasons.push("Claude unavailable");
      return `Debate Mode requires both AIs. ${reasons.join(", ")}`;
    }
    return "";
  };

  const models = useMemo(
    () =>
      [
        { id: "openai", label: "OpenAI", available: isOpenAIAvailable },
        { id: "anthropic", label: "Claude", available: isClaudeAvailable },
        { id: "boost", label: "Debate Mode", available: isDebateModeAvailable },
      ] as const,
    [isOpenAIAvailable, isClaudeAvailable, isDebateModeAvailable]
  );

  const handleSelect = useCallback(
    (id: (typeof models)[number]["id"], available: boolean) => {
      if (!available) return; // Don't allow selection if unavailable

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
        const isAvailable = model.available;
        const unavailableReason = getUnavailableReason(model.id);

        // Define color schemes for each model
        let buttonClasses = "";

        if (!isAvailable) {
          // Disabled state - gray and muted
          buttonClasses =
            "bg-surface/50 text-text-secondary/50 border border-border/50 cursor-not-allowed opacity-60";
        } else if (model.id === "openai") {
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
                onClick={() => handleSelect(model.id, isAvailable)}
                disabled={!isAvailable}
                title={!isAvailable ? unavailableReason : undefined}
                className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-all duration-200 ${
                  isAvailable
                    ? "cursor-pointer hover:scale-105"
                    : "cursor-not-allowed"
                } justify-center ${buttonClasses}`}
              >
                {!isAvailable ? (
                  <LockIcon size={14} className="text-text-secondary/50" />
                ) : (
                  getModelIcon(model.id)
                )}
                <span>{model.label}</span>
                {isAvailable && <ChevronDownIcon size={12} />}
              </button>

              {/* Dropdown menu */}
              {isActive && showModelDropdown && isAvailable && (
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
            onClick={() => handleSelect(model.id, isAvailable)}
            disabled={!isAvailable}
            title={!isAvailable ? unavailableReason : undefined}
            className={`flex items-center gap-2 px-4 py-2 rounded text-sm font-medium transition-all duration-200 ${
              isAvailable
                ? "cursor-pointer hover:scale-105"
                : "cursor-not-allowed"
            } justify-center ${buttonClasses}`}
          >
            {!isAvailable ? (
              <LockIcon size={14} className="text-text-secondary/50" />
            ) : model.id === "boost" ? (
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
