/**
 * DebateView Component
 * Displays the debate rounds and final solution
 */

import React from "react";
import { useDebateStore } from "../../store/debateStore";
import { DebateRound, FinalSolution } from "../../types/debate";
import Skeleton from "../Shared/Skeleton";

// Model badge colors
const MODEL_COLORS = {
  "gpt-4o": "bg-blue-500 text-white",
  "claude-3-5-sonnet": "bg-green-500 text-white",
  "claude-opus-4": "bg-yellow-500 text-gray-900",
};

// Role labels
const ROLE_LABELS = {
  proposer: "Proposer 💡",
  critic: "Critic 🔍",
  defender: "Defender 🛡️",
  judge: "Judge ⚖️",
};

interface RoundCardProps {
  round: DebateRound;
  roundNumber: number;
}

const RoundCard: React.FC<RoundCardProps> = ({ round, roundNumber }) => {
  const modelColor =
    MODEL_COLORS[round.model as keyof typeof MODEL_COLORS] ||
    "bg-gray-500 text-white";

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-4 border-l-4 border-blue-500">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="flex items-center justify-center w-8 h-8 rounded-full bg-blue-100 dark:bg-blue-900 text-blue-600 dark:text-blue-300 font-bold">
            {roundNumber}
          </div>
          <div>
            <div
              className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${modelColor}`}
            >
              {round.model}
            </div>
            <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
              {ROLE_LABELS[round.role]}
            </div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {round.tokens.toLocaleString()} tokens
          </div>
          <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
            ${round.cost.toFixed(4)}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="prose dark:prose-invert max-w-none">
        <div className="text-gray-700 dark:text-gray-300 whitespace-pre-wrap">
          {round.content}
        </div>
      </div>
    </div>
  );
};

interface FinalSolutionCardProps {
  solution: FinalSolution;
}

const FinalSolutionCard: React.FC<FinalSolutionCardProps> = ({ solution }) => {
  const modelColor =
    MODEL_COLORS[solution.model as keyof typeof MODEL_COLORS] ||
    "bg-gray-500 text-white";

  return (
    <div className="bg-gradient-to-r from-yellow-50 to-yellow-100 dark:from-yellow-900 dark:to-yellow-800 rounded-lg shadow-lg p-6 border-2 border-yellow-400 dark:border-yellow-600">
      {/* Header */}
      <div className="flex items-start justify-between mb-4">
        <div className="flex items-center gap-3">
          <div className="text-3xl">🏆</div>
          <div>
            <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-1">
              Final Solution
            </h3>
            <div
              className={`inline-block px-3 py-1 rounded-full text-sm font-medium ${modelColor}`}
            >
              {solution.model}
            </div>
            <span className="ml-2 text-sm text-gray-600 dark:text-gray-400">
              {ROLE_LABELS[solution.role]}
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-gray-600 dark:text-gray-400">
            {solution.tokens.toLocaleString()} tokens
          </div>
          <div className="text-sm font-medium text-gray-900 dark:text-gray-100">
            ${solution.cost.toFixed(4)}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="prose dark:prose-invert max-w-none">
        <div className="text-gray-800 dark:text-gray-200 whitespace-pre-wrap">
          {solution.content}
        </div>
      </div>
    </div>
  );
};

const LoadingSkeleton: React.FC = () => {
  return (
    <div className="space-y-4">
      {[1, 2, 3].map((i) => (
        <div
          key={i}
          className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6"
        >
          <div className="flex items-center gap-3 mb-4">
            <Skeleton className="w-8 h-8 rounded-full" />
            <Skeleton className="w-32 h-6 rounded-full" />
          </div>
          <Skeleton className="w-full h-32 rounded" />
        </div>
      ))}
    </div>
  );
};

export const DebateView: React.FC = () => {
  const {
    isDebating,
    rounds,
    finalSolution,
    topic,
    totalTokens,
    totalCost,
    error,
  } = useDebateStore();

  if (error) {
    return (
      <div className="bg-red-50 dark:bg-red-900 border border-red-200 dark:border-red-700 rounded-lg p-4">
        <div className="flex items-center gap-2">
          <span className="text-2xl">❌</span>
          <div>
            <h3 className="font-bold text-red-900 dark:text-red-100">
              Debate Failed
            </h3>
            <p className="text-sm text-red-700 dark:text-red-200">{error}</p>
          </div>
        </div>
      </div>
    );
  }

  if (isDebating) {
    return (
      <div className="space-y-4">
        <div className="bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-700 rounded-lg p-4">
          <div className="flex items-center gap-3">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-600"></div>
            <div>
              <h3 className="font-bold text-blue-900 dark:text-blue-100">
                Debate in Progress...
              </h3>
              <p className="text-sm text-blue-700 dark:text-blue-200">
                {topic || "Analyzing the topic"}
              </p>
            </div>
          </div>
        </div>
        <LoadingSkeleton />
      </div>
    );
  }

  if (rounds.length === 0 && !finalSolution) {
    return (
      <div className="bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg p-8 text-center">
        <div className="text-6xl mb-4">🎯</div>
        <h3 className="text-xl font-bold text-gray-900 dark:text-white mb-2">
          No Debate Yet
        </h3>
        <p className="text-gray-600 dark:text-gray-400">
          Start a debate to see AI models discuss and find the best solution
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Topic Header */}
      {topic && (
        <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6">
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-2">
            {topic}
          </h2>
          <div className="flex gap-4 text-sm text-gray-600 dark:text-gray-400">
            <span>📊 {rounds.length} rounds</span>
            <span>🎟️ {totalTokens.toLocaleString()} total tokens</span>
            <span>💰 ${totalCost.toFixed(4)} total cost</span>
          </div>
        </div>
      )}

      {/* Rounds Timeline */}
      <div className="space-y-4">
        {rounds.map((round, index) => (
          <RoundCard
            key={round.round_num}
            round={round}
            roundNumber={index + 1}
          />
        ))}
      </div>

      {/* Final Solution */}
      {finalSolution && (
        <div className="mt-6">
          <FinalSolutionCard solution={finalSolution} />
        </div>
      )}
    </div>
  );
};
