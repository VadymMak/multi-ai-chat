// File: src/pages/Landing.tsx

import React from "react";
import { Link } from "react-router-dom";

const Landing: React.FC = () => {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-gradient-to-br from-gray-100 to-blue-100 text-gray-800 p-6">
      <h1 className="text-4xl font-bold mb-4">🧠 Multi-AI Assistant</h1>
      <p className="text-center max-w-xl text-lg mb-6">
        Talk with powerful AI models like OpenAI, Claude, and Grok. You can even
        make them debate each other or answer based on specific memory roles.
      </p>

      <Link
        to="/chat"
        className="bg-blue-600 text-white px-6 py-3 rounded-lg shadow-md hover:bg-blue-700 transition"
      >
        🚀 Enter Chat Interface
      </Link>

      <footer className="mt-12 text-xs text-gray-500">
        © {new Date().getFullYear()} Your AI Assistant • Built with React +
        FastAPI
      </footer>
    </div>
  );
};

export default Landing;
