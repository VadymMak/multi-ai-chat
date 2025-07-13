// src/components/ChatArea/ChatArea.tsx
import React, { useEffect, useRef, useState } from "react";
import styles from "./ChatArea.module.css";
import { Message, Model, YouTubeResult } from "../../types";
import { SiOpenai } from "react-icons/si";
import { GiBrain } from "react-icons/gi";
import { FiZap } from "react-icons/fi";

interface Props {
  messages: (Message & { youtubeResults?: YouTubeResult[] })[];
  isLoading: boolean;
  selectedModel: Model;
}

/* -------- icon helper -------- */
const Icon = ({ model }: { model: string }): React.ReactElement | null => {
  switch (model) {
    case "openai":
      return SiOpenai({ size: 16, color: "#10a37f" }) as React.ReactElement;
    case "anthropic":
      return GiBrain({ size: 16, color: "#8a2be2" }) as React.ReactElement;
    case "grok":
      return FiZap({ size: 16, color: "#facc15" }) as React.ReactElement;
    default:
      return null;
  }
};

const nameMap: Record<string, string> = {
  openai: "ChatGPT",
  anthropic: "Claude",
  grok: "Grok",
  final: "Combined",
};

/* -------- helpers -------- */
const linkify = (txt: string) =>
  txt.replace(
    /(https?:\/\/[^\s]+)/g,
    (m) => `<a href="${m}" target="_blank" rel="noopener noreferrer">${m}</a>`
  );

const YouTubeBlock = ({ vids }: { vids: YouTubeResult[] }) => (
  <div className={styles.youtubeBlock}>
    <h4>YouTube Results:</h4>
    <ul className={styles.youtubeList}>
      {vids.map((v, i) => (
        <li key={i} className={styles.youtubeItem}>
          <a
            href={v.url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.youtubeLink}
          >
            <strong>{v.title}</strong>
          </a>
          {v.description && (
            <p className={styles.youtubeDescription}>{v.description}</p>
          )}
        </li>
      ))}
    </ul>
  </div>
);

/* ===== component ===== */
const ChatArea: React.FC<Props> = ({ messages, isLoading, selectedModel }) => {
  const ref = useRef<HTMLDivElement>(null);
  const [typing, setTyping] = useState("");
  const typingRef = useRef<NodeJS.Timeout | null>(null);

  // Scroll to bottom when messages or typing change
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [messages, typing]);

  // Animate the last AI message only
  useEffect(() => {
    const last = messages.at(-1);
    if (!last || last.sender !== "ai") return;

    if (typingRef.current) clearInterval(typingRef.current);
    setTyping("");

    let i = 0;
    typingRef.current = setInterval(() => {
      i++;
      setTyping(last.text.slice(0, i));
      if (i >= last.text.length && typingRef.current) {
        clearInterval(typingRef.current);
      }
    }, 15);

    return () => {
      if (typingRef.current) clearInterval(typingRef.current);
    };
  }, [messages]);

  return (
    <div className={styles.chatArea} ref={ref}>
      {messages.map((m, idx) => {
        const isLastMessage = idx === messages.length - 1 && m.sender === "ai";
        const showTyping = isLastMessage && typing.length < m.text.length;
        const body = isLastMessage ? typing || m.text : m.text;

        const cleaned = body.startsWith("[Claude Error]")
          ? "Claude is temporarily overloaded – please retry."
          : body.replace(/undefined/g, "");

        return (
          <div
            key={idx}
            className={`${styles.message} ${
              m.sender === "user" ? styles.userMessage : styles.aiMessage
            }`}
          >
            {m.sender === "ai" && m.aiModel && (
              <span className={styles.aiModelTag}>
                <Icon model={m.aiModel} /> {nameMap[m.aiModel] || m.aiModel}
              </span>
            )}

            <div
              className={styles.messageText}
              dangerouslySetInnerHTML={{ __html: linkify(cleaned) }}
            />

            {!showTyping && m.youtubeResults?.length ? (
              <YouTubeBlock vids={m.youtubeResults} />
            ) : null}

            <div className={styles.timestamp}>{m.timestamp}</div>
          </div>
        );
      })}

      {isLoading && (
        <div className={styles.loadingMessage}>
          <div className={styles.thinkingPulse}>
            <Icon model={selectedModel === "all" ? "final" : selectedModel} />
            <span className={styles.aiModelTag}>Thinking…</span>
          </div>
        </div>
      )}
    </div>
  );
};

export default ChatArea;
