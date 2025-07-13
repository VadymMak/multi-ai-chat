import React from "react";
import styles from "./Header.module.css";
import { Model } from "../../types";

interface HeaderProps {
  selectedModel: Model;
  onSelectModel: (model: Model) => void;
  selectedRole: string;
  onSelectRole: (role: string) => void;
}

const roles = [
  "LLM Engineer",
  "Vessel Engineer",
  "ML Engineer",
  "Data Scientist",
  "Frontend Developer",
  "Python Developer",
  "Esoteric Knowledge",
];

const Header: React.FC<HeaderProps> = ({
  selectedModel,
  onSelectModel,
  selectedRole,
  onSelectRole,
}) => (
  <header className={styles.header}>
    <h1 className={styles.title}>Multi-AI Chat</h1>
    <div className={styles.controls}>
      <div className={styles.modelButtons}>
        {(["openai", "anthropic", "grok", "all"] as Model[]).map((model) => (
          <button
            key={model}
            className={`${styles.modelButton} ${
              selectedModel === model ? styles.modelButtonSelected : ""
            }`}
            onClick={() => onSelectModel(model)}
          >
            {model === "grok"
              ? "Grok (xAI)"
              : model === "all"
              ? "All (AI-to-AI)"
              : model.charAt(0).toUpperCase() + model.slice(1)}
          </button>
        ))}
      </div>
      <select
        className={styles.roleSelect}
        value={selectedRole}
        onChange={(e) => onSelectRole(e.target.value)}
      >
        {roles.map((role) => (
          <option key={role} value={role.toLowerCase().replace(" ", "_")}>
            {role}
          </option>
        ))}
      </select>
    </div>
  </header>
);

export default Header;
