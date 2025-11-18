import React from "react";
import { AlertCircle } from "lucide-react";

interface TokenBudgetIndicatorProps {
  usedTokens: number;
  maxTokens: number;
  onSummarize?: () => void;
}

export const TokenBudgetIndicator: React.FC<TokenBudgetIndicatorProps> = ({
  usedTokens,
  maxTokens,
  onSummarize,
}) => {
  const percentage = (usedTokens / maxTokens) * 100;
  const showButton = percentage > 50;

  const getColor = () => {
    if (percentage < 60)
      return "text-green-400 bg-green-400/10 border-green-400/20";
    if (percentage < 80)
      return "text-yellow-400 bg-yellow-400/10 border-yellow-400/20";
    return "text-red-400 bg-red-400/10 border-red-400/20";
  };

  const getBarColor = () => {
    if (percentage < 60) return "bg-green-500";
    if (percentage < 80) return "bg-yellow-500";
    return "bg-red-500";
  };

  const formatTokens = (tokens: number) => {
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}K`;
    return tokens.toString();
  };

  return (
    <div
      className={`
        flex items-center gap-2 px-3 py-1.5 rounded-lg border 
        ${getColor()}
        transition-all duration-300 ease-in-out
      `}
      style={{
        minWidth: showButton ? "220px" : "140px",
      }}
    >
      {percentage > 80 && <AlertCircle className="w-4 h-4 flex-shrink-0" />}

      <div className="flex flex-col gap-1 flex-1 min-w-[90px]">
        <div className="text-xs font-medium whitespace-nowrap">
          {formatTokens(usedTokens)} / {formatTokens(maxTokens)}
        </div>

        <div className="w-full h-1 bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all duration-300 ${getBarColor()}`}
            style={{ width: `${Math.min(percentage, 100)}%` }}
          />
        </div>
      </div>

      {onSummarize && (
        <div
          className="overflow-hidden transition-all duration-300 ease-in-out"
          style={{
            width: showButton ? "auto" : "0px",
            opacity: showButton ? 1 : 0,
          }}
        >
          <button
            onClick={onSummarize}
            disabled={!showButton}
            className={`
              text-xs px-2 py-0.5 rounded whitespace-nowrap
              transition-colors
              ${
                percentage > 80
                  ? "bg-red-500 hover:bg-red-600"
                  : "bg-blue-500 hover:bg-blue-600"
              }
            `}
          >
            Summarize
          </button>
        </div>
      )}
    </div>
  );
};
