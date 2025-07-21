// File: src/utils/isValidSender.ts

import { ChatMessage } from "../types/chat";

export const isValidSender = (s: string): s is ChatMessage["sender"] => {
  return ["user", "openai", "anthropic", "grok"].includes(s);
};
