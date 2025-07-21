// File: src/App.tsx

import React from "react";
import { Link } from "react-router-dom";

const App: React.FC = () => {
  return (
    // <div className="bg-black text-white text-5xl p-20 text-center">
    //   Tailwind is working!
    // </div>

    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 text-gray-800 p-8">
      <h1 className="text-3xl font-bold mb-6">🤖 Multi-AI Assistant</h1>
      <p className="mb-4 text-center max-w-md">
        Welcome to your AI assistant powered by OpenAI, Anthropic, and Grok. You
        can ask questions, switch roles, or initiate an AI-to-AI debate.
      </p>
      <Link
        to="/chat"
        className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
      >
        💬 Enter Chat Interface
      </Link>

      <footer className="mt-10 text-sm text-gray-500">
        © {new Date().getFullYear()} Your Assistant Project
      </footer>
    </div>
  );
};

export default App;
