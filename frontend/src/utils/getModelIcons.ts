// File: src/utils/getModelIcons.ts

import React, { FC } from "react";
import { SiOpenai } from "react-icons/si";
import { GiBrain } from "react-icons/gi";
import { FiZap } from "react-icons/fi";
import type { IconBaseProps } from "react-icons";

export const getModelIcon = (model: string): React.ReactElement | null => {
  switch (model.toLowerCase()) {
    case "openai":
      return React.createElement(SiOpenai as FC<IconBaseProps>, {
        size: 16,
        color: "#10a37f",
      });
    case "anthropic":
    case "claude":
      return React.createElement(GiBrain as FC<IconBaseProps>, {
        size: 16,
        color: "#8a2be2",
      });
    case "grok":
      return React.createElement(FiZap as FC<IconBaseProps>, {
        size: 16,
        color: "#facc15",
      });
    default:
      return null;
  }
};
