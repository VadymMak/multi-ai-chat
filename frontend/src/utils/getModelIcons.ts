// File: src/utils/getModelIcon.ts

import { SiOpenai } from "react-icons/si";
import { GiBrain } from "react-icons/gi";
import { FiZap } from "react-icons/fi";
import React from "react";

export const getModelIcon = (model: string): React.ReactElement | null => {
  switch (model.toLowerCase()) {
    case "openai":
      return SiOpenai({ size: 16, color: "#10a37f" }) as React.ReactElement;
    case "anthropic":
    case "claude":
      return GiBrain({ size: 16, color: "#8a2be2" }) as React.ReactElement;
    case "grok":
      return FiZap({ size: 16, color: "#facc15" }) as React.ReactElement;
    default:
      return null;
  }
};
