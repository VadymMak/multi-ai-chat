import React from "react";
import styles from "./InputBox.module.css";
import { FiSend } from "react-icons/fi";

interface InputBoxProps {
  input: string;
  setInput: (value: string) => void;
  onSend: () => void;
  isLoading: boolean;
}

const InputBox: React.FC<InputBoxProps> = ({
  input,
  setInput,
  onSend,
  isLoading,
}) => {
  console.log("InputBox render - isLoading:", isLoading); // Debug log

  return (
    <div className={styles.inputArea}>
      <div className={styles.inputContainer}>
        <input
          type="text"
          value={input}
          onChange={(e) => {
            console.log("Input changed:", e.target.value); // Debug input
            setInput(e.target.value);
          }}
          onKeyDown={(e) => e.key === "Enter" && onSend()}
          className={styles.input}
          placeholder="Type your message..."
          disabled={isLoading} // Retain but monitor
        />
        <button
          onClick={onSend}
          className={styles.sendButton}
          disabled={isLoading} // Retain but monitor
        >
          <span className={styles.sendIcon}>
            {FiSend({ size: 16 }) as React.ReactElement}
          </span>
        </button>
      </div>
    </div>
  );
};

export default InputBox;
