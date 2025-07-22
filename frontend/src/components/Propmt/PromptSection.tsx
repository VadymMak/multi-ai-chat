// src/components/Prompt/PromptSection.tsx
import React from "react";
import PromptPicker from "./PromptPicker";

interface PromptSectionProps {
  visible: boolean;
  onPromptReady: (prompt: string) => void;
}

const PromptSection: React.FC<PromptSectionProps> = ({
  visible,
  onPromptReady,
}) => {
  if (!visible) return null;

  return (
    <div className="px-4 pt-3">
      <PromptPicker onPromptReady={onPromptReady} />
    </div>
  );
};

export default PromptSection;
