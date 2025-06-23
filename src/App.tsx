import React, { useState } from "react";
import styles from "./App.module.css";

interface Message {
  text: string;
  sender: "user" | "ai";
  aiModel?: "grok" | "openai" | "anthropic";
  timestamp: string;
}

const App: React.FC = () => {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [selectedModel, setSelectedModel] = useState<
    "grok" | "openai" | "anthropic" | "all"
  >("grok");
  const [isLoading, setIsLoading] = useState(false);

  const getTimestamp = () => {
    return new Date().toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  };

  const handleSend = () => {
    if (input.trim()) {
      setMessages([
        ...messages,
        { text: input, sender: "user", timestamp: getTimestamp() },
      ]);
      setInput("");
      setIsLoading(true);

      setTimeout(() => {
        setMessages((prev) => [
          ...prev,
          {
            text: `Response from ${selectedModel}`,
            sender: "ai",
            aiModel: selectedModel !== "all" ? selectedModel : undefined,
            timestamp: getTimestamp(),
          },
        ]);
        setIsLoading(false);
      }, 1000);
    }
  };

  return (
    <div className={styles.app}>
      {/* Header */}
      <header className={styles.header}>
        <h1 className={styles.title}>Multi-AI Chat</h1>
        <div className={styles.modelButtons}>
          {["grok", "openai", "anthropic", "all"].map((model) => (
            <button
              key={model}
              className={`${styles.modelButton} ${
                selectedModel === model ? styles.modelButtonSelected : ""
              }`}
              onClick={() =>
                setSelectedModel(
                  model as "grok" | "openai" | "anthropic" | "all"
                )
              }
            >
              {model === "grok"
                ? "Grok (xAI)"
                : model === "all"
                ? "All (AI-to-AI)"
                : model.charAt(0).toUpperCase() + model.slice(1)}
            </button>
          ))}
        </div>
      </header>

      {/* Chat Area */}
      <div className={styles.chatArea}>
        {messages.map((msg, idx) => (
          <div
            key={idx}
            className={`${styles.message} ${
              msg.sender === "user" ? styles.userMessage : styles.aiMessage
            }`}
          >
            {msg.sender === "ai" && msg.aiModel && (
              <span className={styles.aiModelTag}>[{msg.aiModel}] </span>
            )}
            <div className={styles.messageText}>{msg.text}</div>
            <div className={styles.timestamp}>{msg.timestamp}</div>
          </div>
        ))}
        {isLoading && (
          <div className={styles.loadingMessage}>
            <span className={styles.aiModelTag}>
              [{selectedModel}] Thinking...
            </span>
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className={styles.inputArea}>
        <div className={styles.inputContainer}>
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => e.key === "Enter" && !isLoading && handleSend()}
            className={styles.input}
            placeholder="Type your message..."
            disabled={isLoading}
          />
          <button
            onClick={handleSend}
            className={styles.sendButton}
            disabled={isLoading}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
};

export default App;
