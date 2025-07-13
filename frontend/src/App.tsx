import React, { useState } from "react";
import styles from "./App.module.css";
import Header from "./components/Header/Header";
import ChatArea from "./components/ChartArea/ChatArea";
import InputBox from "./components/InputArea/InputBox";
import { Model } from "./types";
import { useAiChat } from "./hooks/useAiChat";

const App: React.FC = () => {
  const { messages, isLoading, askLLM, askAiToAi } = useAiChat();
  const [input, setInput] = useState("");
  const [selectedModel, setSelectedModel] = useState<Model>("all");
  const [selectedRole, setSelectedRole] = useState("llm_engineer");

  const handleSend = async () => {
    if (!input.trim() || isLoading) return;
    const prompt = input;
    setInput("");
    try {
      if (selectedModel === "all") {
        await askAiToAi(prompt, selectedRole);
      } else {
        await askLLM(prompt, selectedModel, selectedRole);
      }
    } catch (error) {
      console.error("Error:", error);
    }
  };

  return (
    <div className={styles.app}>
      <Header
        selectedModel={selectedModel}
        onSelectModel={setSelectedModel}
        selectedRole={selectedRole}
        onSelectRole={setSelectedRole}
      />
      <ChatArea
        messages={messages}
        isLoading={isLoading}
        selectedModel={selectedModel}
      />
      <InputBox
        input={input}
        setInput={setInput}
        onSend={handleSend}
        isLoading={isLoading}
      />
    </div>
  );
};

export default App;
