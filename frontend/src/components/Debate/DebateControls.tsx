/**
 * DebateControls Component
 * Controls for starting and managing debates
 */

import React, { useState } from "react";
import { useDebateStore } from "../../store/debateStore";

interface DebateControlsProps {
  initialTopic?: string;
  onTopicChange?: (topic: string) => void;
  onError?: (error: Error) => void;
}

export const DebateControls: React.FC<DebateControlsProps> = ({
  initialTopic = "",
  onTopicChange,
  onError,
}) => {
  const { isDebating, startDebate } = useDebateStore();
  const [topic, setTopic] = useState(initialTopic);
  const [rounds, setRounds] = useState(3);

  const handleTopicChange = (value: string) => {
    setTopic(value);
    onTopicChange?.(value);
  };

  const handleStartDebate = async () => {
    if (!topic.trim()) {
      return;
    }

    try {
      await startDebate(topic, rounds);
} catch (error) {
      console.error("Debate error:", error);
      if (error instanceof Error) {
        onError?.(error);
      }
    }
  };

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-md p-6 mb-6">
      <h3 className="text-lg font-bold text-gray-900 dark:text-white mb-4">
        🎯 Start a Debate
      </h3>

      {/* Topic Input */}
      <div className="mb-4">
        <label
          htmlFor="debate-topic"
          className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2"
        >
          Topic or Question
        </label>
        <textarea
          id="debate-topic"
          value={topic}
          onChange={(e) => handleTopicChange(e.target.value)}
          placeholder="Enter your question or topic for debate..."
          className="w-full px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent dark:bg-gray-700 dark:text-white resize-none"
          rows={3}
          disabled={isDebating}
        />
      </div>

      {/* Rounds Selector */}
      <div className="mb-4">
        <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-2">
          Number of Rounds
        </label>
        <div className="flex gap-2">
          {[2, 3, 5].map((num) => (
            <button
              key={num}
              onClick={() => setRounds(num)}
              disabled={isDebating}
              className={`px-4 py-2 rounded-lg font-medium transition-colors ${
                rounds === num
                  ? "bg-blue-500 text-white"
                  : "bg-gray-200 dark:bg-gray-700 text-gray-700 dark:text-gray-300 hover:bg-gray-300 dark:hover:bg-gray-600"
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {num}
            </button>
          ))}
        </div>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
          3 rounds recommended (2 arguments + 1 final synthesis)
        </p>
      </div>

      {/* Start Button */}
      <button
        onClick={handleStartDebate}
        disabled={isDebating || !topic.trim()}
        className="w-full px-6 py-3 bg-gradient-to-r from-blue-500 to-purple-600 text-white font-semibold rounded-lg hover:from-blue-600 hover:to-purple-700 disabled:opacity-50 disabled:cursor-not-allowed transition-all flex items-center justify-center gap-2"
      >
        {isDebating ? (
          <>
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white"></div>
            <span>
              Debating... Round {rounds} of {rounds}
            </span>
          </>
        ) : (
          <>
            <span>🚀</span>
            <span>Start Debate</span>
          </>
        )}
      </button>

      {/* Info */}
      {!isDebating && (
        <div className="mt-4 p-3 bg-blue-50 dark:bg-blue-900 border border-blue-200 dark:border-blue-700 rounded-lg">
          <p className="text-sm text-blue-900 dark:text-blue-100">
            <strong>How it works:</strong> GPT-4o and Claude Sonnet will debate
            your topic, then Claude Opus will synthesize the best solution.
          </p>
        </div>
      )}
    </div>
  );
};