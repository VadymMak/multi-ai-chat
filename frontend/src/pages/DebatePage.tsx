/**
 * DebatePage Component
 * Main page for Debate Mode
 */

import React from "react";
import { DebateControls } from "../components/Debate/DebateControls";
import { DebateView } from "../components/Debate/DebateView";

export const DebatePage: React.FC = () => {
  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900 py-8 px-4">
      <div className="max-w-5xl mx-auto">
        {/* Page Header */}
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-bold text-gray-900 dark:text-white mb-2">
            🎭 AI Debate Mode
          </h1>
          <p className="text-gray-600 dark:text-gray-400">
            Watch GPT-4o and Claude debate your question, then get the best
            solution
          </p>
        </div>

        {/* Controls */}
        <DebateControls />

        {/* Results */}
        <DebateView />
      </div>
    </div>
  );
};

export default DebatePage;
