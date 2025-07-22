// File: src/pages/Chat/AiChat.tsx
import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  useMemo,
} from "react";
import ChatArea from "../../components/Chat/ChatArea";
import HeaderControls from "../../components/Chat/HeaderControls";
import InputBar from "../../components/Chat/InputBar";
import PromptSection from "../../components/Propmt/PromptSection";
import RoleSelector from "../../components/Selectors/RoleSelector";
import { useStreamText } from "../../hooks/useStreamText";
import { useChatStore } from "../../store/chatStore";
import { useModelStore } from "../../store/modelStore";
import { useProjectStore } from "../../store/projectStore";
import { sendAiMessage, sendAiToAiMessage } from "../../services/aiApi";
import { v4 as uuidv4 } from "uuid";
import { isValidSender } from "../../utils/isValidSender";
import type { SupportedProvider } from "../../types/providers";

const AiChat: React.FC = () => {
  const [input, setInput] = useState("");
  const [showPromptPicker, setShowPromptPicker] = useState(false);
  const [selectedRoleId, setSelectedRoleId] = useState<number>(1);
  const [waitingSession, setWaitingSession] = useState(false);

  const abortRef = useRef<AbortController | null>(null);

  const provider = useModelStore((s) => s.provider);
  const projectId = useProjectStore((s) => s.projectId);
  const safeProjectId = useMemo(() => projectId ?? 1, [projectId]);

  const addMessage = useChatStore((s) => s.addMessage);
  const setTyping = useChatStore((s) => s.setTyping);
  const waitForSessionReady = useChatStore((s) => s.waitForSessionReady);
  const streamText = useStreamText();

  useEffect(() => {
    const prevent = (e: Event) => {
      e.preventDefault();
      e.stopPropagation();
    };
    const handleDrop = (e: DragEvent) => {
      prevent(e);
      console.log("[Global] Prevented file from being opened in browser.");
    };
    document.addEventListener("dragenter", prevent);
    document.addEventListener("dragover", prevent);
    document.addEventListener("dragleave", prevent);
    document.addEventListener("drop", handleDrop);
    return () => {
      document.removeEventListener("dragenter", prevent);
      document.removeEventListener("dragover", prevent);
      document.removeEventListener("dragleave", prevent);
      document.removeEventListener("drop", handleDrop);
    };
  }, []);

  const renderSupplementary = useCallback(
    (type: "youtube" | "web", data?: any[]) => {
      if (!Array.isArray(data)) return;
      const formatted =
        type === "youtube"
          ? data.map((v) => `▶️ [${v.title}](${v.url})`).join("\n\n")
          : data
              .map((v) => `🌐 [${v.title}](${v.url})\n${v.snippet}`)
              .join("\n\n");
      if (!formatted.trim()) return;

      const id = `${type}-${uuidv4()}`;
      addMessage({ id, sender: type, text: "", isTyping: true });
      streamText(id, formatted, abortRef.current!.signal);
    },
    [addMessage, streamText]
  );

  const handleBoostMode = useCallback(
    async (query: string) => {
      await waitForSessionReady(selectedRoleId, safeProjectId);

      const response = await sendAiToAiMessage(
        query,
        "openai",
        selectedRoleId,
        safeProjectId
      );

      const firstMsg = response.messages[0];
      if (firstMsg) {
        const id = `${firstMsg.sender}-${uuidv4()}`;
        const sender = isValidSender(firstMsg.sender)
          ? firstMsg.sender
          : "openai";
        addMessage({ id, sender, text: "", isTyping: true });
        await streamText(
          id,
          firstMsg.text || "⚠️ Empty response.",
          abortRef.current!.signal
        );
      }

      const summaryMsg = response.messages[2];
      if (summaryMsg?.text?.trim()) {
        const id = `${summaryMsg.sender}-${uuidv4()}`;
        const sender = isValidSender(summaryMsg.sender)
          ? summaryMsg.sender
          : "openai";
        addMessage({
          id,
          sender,
          text: "",
          isTyping: true,
          isSummary: true,
        });
        await streamText(id, summaryMsg.text, abortRef.current!.signal);
      }

      renderSupplementary("youtube", response.youtube);
      renderSupplementary("web", response.web);
    },
    [
      addMessage,
      selectedRoleId,
      safeProjectId,
      waitForSessionReady,
      streamText,
      renderSupplementary,
    ]
  );

  const handleSingleModel = useCallback(
    async (query: string) => {
      await waitForSessionReady(selectedRoleId, safeProjectId);

      const fallback: SupportedProvider =
        provider === "grok" || provider === "boost" ? "openai" : provider;

      const response = await sendAiMessage(
        query,
        fallback,
        String(selectedRoleId),
        safeProjectId
      );

      const sender = isValidSender(provider) ? provider : "openai";
      const id = `${sender}-${uuidv4()}`;
      addMessage({ id, sender, text: "", isTyping: true });

      await streamText(
        id,
        response.messages[1]?.text || "No response received.",
        abortRef.current!.signal
      );
    },
    [
      provider,
      selectedRoleId,
      safeProjectId,
      addMessage,
      waitForSessionReady,
      streamText,
    ]
  );

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    setWaitingSession(true);
    try {
      await waitForSessionReady(selectedRoleId, safeProjectId);
    } catch (err) {
      console.error("⏳ Session not ready, aborting send:", err);
      setWaitingSession(false);
      return;
    }
    setWaitingSession(false);

    abortRef.current?.abort();
    abortRef.current = new AbortController();

    const id = `user-${uuidv4()}`;
    addMessage({ id, sender: "user", text: trimmed });
    setInput("");
    setTyping(true);

    try {
      if (provider === "boost") {
        await handleBoostMode(trimmed);
      } else {
        await handleSingleModel(trimmed);
      }
    } catch (err) {
      console.error("AI request failed:", err);
      addMessage({
        id: `error-${uuidv4()}`,
        sender: "openai",
        text: "⚠️ Failed to get a response from the AI.",
      });
    } finally {
      setTyping(false);
    }
  }, [
    input,
    provider,
    handleBoostMode,
    handleSingleModel,
    addMessage,
    setTyping,
    waitForSessionReady,
    selectedRoleId,
    safeProjectId,
  ]);

  const handlePromptInject = useCallback(
    (finalPrompt: string) => {
      setInput(finalPrompt);
      setShowPromptPicker(false);
      setTimeout(() => handleSend(), 100);
    },
    [handleSend]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend]
  );

  const handleAbortTyping = useCallback(() => {
    abortRef.current?.abort();
    useChatStore.getState().setTyping(false);
  }, []);

  const handleFileDrop = useCallback(
    async (file: File): Promise<string | null> => {
      await waitForSessionReady(selectedRoleId, safeProjectId);
      const formData = new FormData();
      formData.append("file", file);

      const url = `http://localhost:8000/api/upload?role_id=${selectedRoleId}&project_id=${safeProjectId}`;

      try {
        const response = await fetch(url, { method: "POST", body: formData });
        const raw = await response.text();
        console.log("📥 Raw response text:", raw);

        if (!response.ok) {
          console.error("❌ Upload failed:", response.status);
          setInput(
            `📎 Uploaded: ${file.name}\n\n⚠️ Server error ${response.status}`
          );
          return null;
        }

        try {
          const data = JSON.parse(raw);
          const filename = data.filename || file.name;
          const summary = data.summary || "⚠️ No summary provided by backend.";
          const injected =
            `📎 Uploaded: ${filename}\n\n🧠 Summary:\n${summary}`.slice(
              0,
              4000
            );
          setInput(injected);
          return injected;
        } catch {
          setInput(`📎 Uploaded: ${file.name}\n\n⚠️ Invalid JSON from server.`);
          return null;
        }
      } catch (err) {
        console.error("❌ Upload failed:", err);
        setInput(
          `📎 Uploaded: ${file.name}\n\n⚠️ Upload failed. Check internet or try again.`
        );
        return null;
      }
    },
    [selectedRoleId, safeProjectId, waitForSessionReady]
  );

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <HeaderControls />
      <PromptSection
        visible={showPromptPicker}
        onPromptReady={handlePromptInject}
      />
      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        <RoleSelector
          selectedRole={selectedRoleId}
          onChange={setSelectedRoleId}
        />
        {!waitingSession ? (
          <ChatArea />
        ) : (
          <div className="text-center text-sm text-gray-500 py-6 animate-pulse">
            ⏳ Initializing session…
          </div>
        )}
      </main>
      <InputBar
        input={input}
        setInput={setInput}
        handleSend={handleSend}
        handleKeyDown={handleKeyDown}
        onAbortTyping={handleAbortTyping}
        onFileDrop={handleFileDrop}
      />
    </div>
  );
};

export default AiChat;
