import { create } from "zustand";
import { toast } from "./toastStore";

interface ChatSettings {
  maxTokens: number;
  lastUsedTokens: number;
  tokenSource: "baseline" | "boosted" | "manual";

  setMaxTokens: (
    tokens: number,
    source?: "baseline" | "boosted" | "manual"
  ) => void;
  setLastUsedTokens: (tokens: number) => void;
}

export const useChatSettingsStore = create<ChatSettings>((set, get) => ({
  maxTokens: 8192,
  lastUsedTokens: 8192,
  tokenSource: "baseline",

  setMaxTokens: (tokens, source = "baseline") => {
    const oldTokens = get().maxTokens;
    const oldSource = get().tokenSource;

    set({ maxTokens: tokens, tokenSource: source });

    // Show toast if changed significantly
    if (Math.abs(tokens - oldTokens) >= 2000 && source !== oldSource) {
      if (source === "boosted") {
        toast.info(
          `⚡ Token limit boosted to ${tokens.toLocaleString()} for code generation`
        );
      } else if (oldSource === "boosted") {
        toast.info(
          `📊 Token limit reset to baseline: ${tokens.toLocaleString()}`
        );
      }
    }
  },

  setLastUsedTokens: (tokens) => {
    set({ lastUsedTokens: tokens });
  },
}));

// Export for console access (development only)
if (typeof window !== "undefined") {
  (window as any).__chatSettings__ = useChatSettingsStore;
}
