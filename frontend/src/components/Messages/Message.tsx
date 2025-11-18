import React from "react";
import { Message } from "../../types";
import styles from "./Message.module.css";

const MessageComponent: React.FC<{ message: Message }> = ({ message }) => (
  <div
    className={`${styles.message} ${
      message.sender === "user" ? styles.userMessage : styles.aiMessage
    }`}
  >
    {message.sender === "ai" && message.aiModel && (
      <span className={styles.aiModelTag}>[{message.aiModel}] </span>
    )}
    <div className={styles.messageText}>{message.text}</div>
    <div className={styles.timestamp}>{message.timestamp}</div>
  </div>
);

export default MessageComponent;
