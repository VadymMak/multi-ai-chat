// File: src/utils/isValidModelProvider.ts

import type { ModelProvider } from "../store/modelStore";

export const isValidModelProvider = (val: string): val is ModelProvider => {
  return ["openai", "anthropic", "grok"].includes(val);
};
