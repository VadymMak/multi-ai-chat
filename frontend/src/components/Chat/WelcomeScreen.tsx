import React from "react";

interface WelcomeScreenProps {
  onCreateProject: () => void;
}

export const WelcomeScreen: React.FC<WelcomeScreenProps> = ({
  onCreateProject,
}) => {
  return (
    <div className="flex items-center justify-center h-full bg-gradient-to-b from-gray-900 to-gray-800">
      <div className="max-w-2xl mx-auto px-6 py-12 text-center">
        {/* Main Welcome */}
        <div className="mb-8">
          <h1 className="text-4xl font-bold text-white mb-4">
            👋 Welcome to Multi-AI Chat!
          </h1>
          <p className="text-xl text-gray-300">
            Your intelligent assistant for conversations with multiple AI models
          </p>
        </div>

        {/* Features */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-10">
          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <div className="text-4xl mb-3">📁</div>
            <h3 className="text-white font-semibold mb-2">Organize Projects</h3>
            <p className="text-gray-400 text-sm">
              Create projects to organize conversations by topic or purpose
            </p>
          </div>

          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <div className="text-4xl mb-3">💬</div>
            <h3 className="text-white font-semibold mb-2">
              Choose AI Assistant
            </h3>
            <p className="text-gray-400 text-sm">
              Pick from multiple AI models optimized for different tasks
            </p>
          </div>

          <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
            <div className="text-4xl mb-3">⚡</div>
            <h3 className="text-white font-semibold mb-2">Debate Mode</h3>
            <p className="text-gray-400 text-sm">
              Compare responses from different AI models side-by-side
            </p>
          </div>
        </div>

        {/* CTA */}
        <div className="space-y-4">
          <button
            onClick={onCreateProject}
            className="w-full md:w-auto px-8 py-4 bg-blue-600 hover:bg-blue-700 text-white text-lg font-semibold rounded-lg transition-colors duration-200 shadow-lg hover:shadow-xl"
          >
            🚀 Create Your First Project
          </button>

          <p className="text-gray-400 text-sm">
            💡 Tip: You can create multiple projects to organize different
            topics
          </p>
        </div>
      </div>
    </div>
  );
};
