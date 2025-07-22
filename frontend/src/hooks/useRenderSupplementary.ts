import { v4 as uuidv4 } from "uuid";
import { useChatStore } from "../store/chatStore";
import { useStreamText } from "./useStreamText";
import type { Sender } from "../types/chat";

export const useRenderSupplementary = () => {
  const addMessage = useChatStore((s) => s.addMessage);
  const streamText = useStreamText();

  const renderSupplementary = async (
    type: "youtube" | "web",
    data: any,
    abortSignal?: AbortSignal
  ) => {
    const id = `${type}-${uuidv4()}`;
    const sender = type as Sender;

    let text = "";
    if (Array.isArray(data)) {
      text = data
        .map((v) =>
          type === "youtube"
            ? `▶️ [${v.title}](${v.url})`
            : `🌐 [${v.title}](${v.url})\n${v.snippet || ""}`
        )
        .join("\n\n");
    } else {
      text = `⚠️ Invalid ${type} results format.`;
    }

    addMessage({ id, sender, text: "", isTyping: true });
    await streamText(id, text, abortSignal);
  };

  return { renderSupplementary };
};
