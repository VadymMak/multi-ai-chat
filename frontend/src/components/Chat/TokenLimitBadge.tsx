import React, { useState } from "react";
import { Zap, Info } from "lucide-react";
import { useChatSettingsStore } from "../../store/chatSettingsStore";
import { calculateCost } from "../../utils/calculateCost";

interface TokenLimitBadgeProps {
  model?: string;
}

export const TokenLimitBadge: React.FC<TokenLimitBadgeProps> = ({
  model = "gpt-4o-mini",
}) => {
  const [showTooltip, setShowTooltip] = useState(false);
  const maxTokens = useChatSettingsStore((state) => state.maxTokens);
  const tokenSource = useChatSettingsStore((state) => state.tokenSource);

  // Calculate cost - assume 50/50 split between input/output tokens for estimate
  const estimatedInputTokens = Math.floor(maxTokens * 0.5);
  const estimatedOutputTokens = Math.floor(maxTokens * 0.5);
  const cost = calculateCost(
    estimatedInputTokens,
    estimatedOutputTokens,
    model
  );

  // Format tokens same as budget (e.g., 8192 → "8.2K")
  const formatTokens = (tokens: number): string => {
    if (tokens >= 1000) {
      return `${(tokens / 1000).toFixed(1)}K`;
    }
    return tokens.toString();
  };

  // Background color (matching budget style)
  const getBgColor = (): string => {
    if (maxTokens >= 16000) return "bg-purple-900/30";
    if (maxTokens >= 12000) return "bg-blue-900/30";
    if (maxTokens >= 10000) return "bg-green-900/30";
    return "bg-gray-800/50";
  };

  // Border color (matching budget style)
  const getBorderColor = (): string => {
    if (maxTokens >= 16000) return "border-purple-700";
    if (maxTokens >= 12000) return "border-blue-700";
    if (maxTokens >= 10000) return "border-green-700";
    return "border-gray-700";
  };

  // Text color
  const getTextColor = (): string => {
    if (maxTokens >= 16000) return "text-purple-400";
    if (maxTokens >= 12000) return "text-blue-400";
    if (maxTokens >= 10000) return "text-green-400";
    return "text-gray-400";
  };

  // Underline indicator color (NEW!)
  const getIndicatorColor = (): string => {
    if (maxTokens >= 16000) return "bg-purple-500";
    if (maxTokens >= 12000) return "bg-blue-500";
    if (maxTokens >= 10000) return "bg-green-500";
    return "bg-gray-500";
  };

  // Icon
  const getIcon = () => {
    if (tokenSource === "boosted") {
      return <Zap size={16} className="animate-pulse" />;
    }
    return <Info size={16} />;
  };

  return (
    <div className="relative">
      {/* Badge - EXACT same structure as TokenBudgetIndicator */}
      <button
        className={`
          relative flex items-center gap-2 
          px-4 py-2 rounded-lg border
          text-sm font-medium
          transition-all hover:opacity-90
          ${getBgColor()} 
          ${getBorderColor()} 
          ${getTextColor()}
        `}
        onMouseEnter={() => setShowTooltip(true)}
        onMouseLeave={() => setShowTooltip(false)}
        onClick={() => setShowTooltip(!showTooltip)}
      >
        {/* Icon */}
        {getIcon()}

        {/* Text - format like budget: "8.2K | ~$0.02" */}
        <span className="whitespace-nowrap">
          {formatTokens(maxTokens)}
          <span className="text-gray-400 ml-1">| ~{cost}</span>
        </span>

        {/* Underline indicator - SAME as budget! */}
        <div
          className={`
            absolute bottom-0 left-0 right-0 h-0.5 rounded-full
            ${getIndicatorColor()}
          `}
        />
      </button>

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute top-full right-0 mt-2 p-3 bg-gray-800 border border-gray-700 rounded-lg shadow-xl z-50 w-72">
          <div className="space-y-3 text-xs">
            {/* Header */}
            <div className="flex items-center justify-between pb-2 border-b border-gray-700">
              <span className="text-gray-400 font-medium">Token Limit</span>
              <span className={`font-bold ${getTextColor()}`}>
                {maxTokens.toLocaleString()}
              </span>
            </div>

            {/* Details */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-gray-400">Source:</span>
                <span className="text-white capitalize">{tokenSource}</span>
              </div>

              <div className="flex items-center justify-between">
                <span className="text-gray-400">Status:</span>
                <span className={getTextColor()}>
                  {maxTokens >= 16000
                    ? "⚡ Maximum"
                    : maxTokens >= 12000
                    ? "🔥 High"
                    : maxTokens >= 10000
                    ? "✓ Medium"
                    : "• Standard"}
                </span>
              </div>
            </div>

            {/* Description */}
            <div className="pt-2 border-t border-gray-700">
              <p className="text-gray-300 leading-relaxed">
                {tokenSource === "boosted" && (
                  <>⚡ Auto-boosted for complex code generation</>
                )}
                {tokenSource === "baseline" && (
                  <>📊 Based on project and role context</>
                )}
                {tokenSource === "manual" && (
                  <>🔒 Manually configured in settings</>
                )}
              </p>
            </div>

            <div className="text-gray-500 text-xs pt-1">
              Higher limits prevent code truncation
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
