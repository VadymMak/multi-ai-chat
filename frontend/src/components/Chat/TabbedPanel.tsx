import React, { useState, lazy, Suspense } from "react";

const PromptPicker = lazy(() => import("../Propmt/PromptPicker"));
const ChatHistoryPanel = lazy(() => import("./ChatHistoryPanel"));

interface TabbedPanelProps {
  onPromptReady: (prompt: string) => void;
}

const TabbedPanel: React.FC<TabbedPanelProps> = ({ onPromptReady }) => {
  const [activeTab, setActiveTab] = useState<"chat" | "prompt" | "history">(
    "chat"
  );

  const getButtonClass = (tab: string) =>
    `px-3 py-1.5 text-sm rounded-md font-medium transition-all duration-150 
     ${
       activeTab === tab
         ? "bg-blue-600 text-white shadow-md"
         : "bg-white text-gray-700 border border-gray-300 hover:bg-gray-100"
     }`;

  return (
    <div className="flex flex-col h-full border-b border-gray-200 bg-gray-50">
      {/* Tab Buttons */}
      <div className="flex gap-2 px-3 py-2 flex-wrap">
        <button
          className={getButtonClass("chat")}
          onClick={() => setActiveTab("chat")}
          role="tab"
          aria-selected={activeTab === "chat"}
        >
          💬 Chat
        </button>
        <button
          className={getButtonClass("prompt")}
          onClick={() => setActiveTab("prompt")}
          role="tab"
          aria-selected={activeTab === "prompt"}
        >
          📚 Prompt Library
        </button>
        <button
          className={getButtonClass("history")}
          onClick={() => setActiveTab("history")}
          role="tab"
          aria-selected={activeTab === "history"}
        >
          🧠 History
        </button>
      </div>

      {/* Tab Content */}
      <div
        className="flex-1 overflow-y-auto px-4 py-3 bg-white"
        role="tabpanel"
      >
        <Suspense
          fallback={<div className="text-sm text-gray-500">Loading…</div>}
        >
          {activeTab === "chat" && (
            <div className="text-sm text-gray-500">
              🧾 Chat messages appear in the center pane ➡️
            </div>
          )}
          {activeTab === "prompt" && (
            <PromptPicker onPromptReady={onPromptReady} />
          )}
          {activeTab === "history" && <ChatHistoryPanel />}
        </Suspense>
      </div>
    </div>
  );
};

export default TabbedPanel;
