import React, { useState } from "react";
import ChatArea from "../../components/Chat/ChatArea";
import AiSelector from "./AiSelector";
import MemoryRoleSelector from "./MemoryRoleSelector";
import { useChatStore } from "../../store/chatStore";
import { useModelStore } from "../../store/modelStore";
import { sendAiMessage, sendAiToAiMessage } from "../../services/aiApi";
import { v4 as uuidv4 } from "uuid";
import { isValidSender } from "../../utils/isValidSender";

const AiChat: React.FC = () => {
  const [input, setInput] = useState("");
  const provider = useModelStore((state) => state.provider);
  const addMessage = useChatStore((state) => state.addMessage);
  const setTyping = useChatStore((state) => state.setTyping);

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const userMsg = {
      id: uuidv4(),
      sender: "user" as const,
      text: trimmed,
    };

    addMessage(userMsg);
    setInput("");
    setTyping(true);

    try {
      if (provider === "boost") {
        const response = await sendAiToAiMessage(trimmed, "openai");

        // Stream each individual AI response
        if (Array.isArray(response.messages)) {
          for (const msg of response.messages) {
            const id = uuidv4();
            const sender = isValidSender(msg.sender) ? msg.sender : "openai";
            addMessage({
              id,
              sender,
              text: "",
              isTyping: true,
              isSummary: false,
            });
            await streamText(id, msg.answer || "⚠️ Empty response.");
          }
        }

        // Stream final summary (if exists)
        const finalSummary = response.summary?.trim();
        const summaryId = uuidv4();
        if (finalSummary) {
          addMessage({
            id: summaryId,
            sender: "anthropic",
            text: "",
            isTyping: true,
            isSummary: true,
          });
          await streamText(summaryId, finalSummary);
        } else {
          addMessage({
            id: summaryId,
            sender: "anthropic",
            text: "🧾 No summary provided.",
            isSummary: true,
          });
        }
      } else {
        // Single AI mode
        const response = await sendAiMessage(trimmed);
        const sender = isValidSender(response.provider)
          ? response.provider
          : "openai";
        const id = uuidv4();
        addMessage({ id, sender, text: "", isTyping: true });
        await streamText(id, response.answer || "No response received.");
      }
    } catch (err) {
      console.error("AI request failed:", err);
      addMessage({
        id: uuidv4(),
        sender: "openai",
        text: "⚠️ Failed to get a response from the AI.",
      });
    } finally {
      setTyping(false);
    }
  };

  const streamText = async (id: string, fullText: string) => {
    const delay = 10; // ms per character
    for (let i = 1; i <= fullText.length; i++) {
      await new Promise((res) => setTimeout(res, delay));
      useChatStore.getState().updateMessageText(id, fullText.slice(0, i));
    }
    useChatStore.getState().markMessageDone(id);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      {/* Header */}
      <div className="sticky top-0 z-10 bg-white border-b p-3 shadow-sm">
        <div className="flex flex-wrap gap-2 justify-center sm:justify-start mb-2">
          <AiSelector />
        </div>
        <div className="flex flex-wrap gap-2 justify-center sm:justify-start">
          <MemoryRoleSelector />
        </div>
      </div>

      {/* Chat area */}
      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        <ChatArea />
      </main>

      {/* Input bar */}
      <footer className="p-4 border-t bg-white">
        <div className="max-w-4xl mx-auto w-full px-4">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSend();
            }}
            className="flex flex-col gap-2"
          >
            <label htmlFor="chat-input" className="text-sm text-gray-600">
              💬 Ask something to your selected AI
            </label>
            <div className="flex gap-2">
              <input
                id="chat-input"
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask something..."
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg shadow-sm focus:outline-none focus:ring-2 focus:ring-blue-500 placeholder:text-left placeholder:text-gray-400 text-sm"
              />
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
              >
                Send
              </button>
            </div>
          </form>
        </div>
      </footer>
    </div>
  );
};

export default AiChat;
