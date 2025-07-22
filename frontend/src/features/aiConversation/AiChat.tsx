import React, { useState, useRef, useEffect } from "react";
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

  const abortRef = useRef<AbortController | null>(null);

  const provider = useModelStore((s) => s.provider);
  const projectId = useProjectStore((s) => s.projectId);

  const addMessage = useChatStore((s) => s.addMessage);
  const setTyping = useChatStore((s) => s.setTyping);
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

  const handleSend = async () => {
    const trimmed = input.trim();
    if (!trimmed) return;

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
  };

  const handleBoostMode = async (query: string) => {
    const response = await sendAiToAiMessage(
      query,
      "openai",
      String(selectedRoleId),
      projectId
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
      addMessage({
        id,
        sender: summaryMsg.sender,
        text: "",
        isTyping: true,
        isSummary: true,
      });
      await streamText(id, summaryMsg.text, abortRef.current!.signal);
    }

    renderSupplementary("youtube", response.youtube);
    renderSupplementary("web", response.web);
  };

  const handleSingleModel = async (query: string) => {
    const fallback: SupportedProvider =
      provider === "grok" || provider === "boost" ? "openai" : provider;
    const response = await sendAiMessage(
      query,
      fallback,
      String(selectedRoleId),
      projectId
    );

    const sender = isValidSender(response.provider)
      ? response.provider
      : "openai";
    const id = `${sender}-${uuidv4()}`;
    addMessage({ id, sender, text: "", isTyping: true });
    await streamText(
      id,
      response.answer || "No response received.",
      abortRef.current!.signal
    );
  };

  const handlePromptInject = (finalPrompt: string) => {
    setInput(finalPrompt);
    setShowPromptPicker(false);
    setTimeout(() => handleSend(), 100);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleAbortTyping = () => {
    abortRef.current?.abort();
    useChatStore.getState().setTyping(false);
  };

  const handleFileDrop = async (file: File) => {
    const formData = new FormData();
    formData.append("file", file);

    const projId =
      typeof projectId === "number"
        ? projectId
        : projectId && typeof projectId === "object" && "id" in projectId
        ? (projectId as { id: number }).id
        : 1;

    const url = `http://localhost:8000/api/upload?role_id=${selectedRoleId}&project_id=${projId}`;

    try {
      const response = await fetch(url, {
        method: "POST",
        body: formData,
      });

      const raw = await response.text();
      console.log("📥 Raw response text:", raw);

      if (!response.ok) {
        console.error("❌ Upload failed with HTTP status:", response.status);
        setInput(
          `📎 Uploaded: ${file.name || "Unknown file"}\n\n⚠️ Server error ${
            response.status
          }: Unable to process the file.`
        );
        return;
      }

      try {
        const data = JSON.parse(raw);
        console.log("✅ Parsed upload response:", data);

        const filename = data.filename || "Unknown file";
        const summary = data.summary || "⚠️ No summary provided by backend.";

        const display = `📎 Uploaded: ${filename}\n\n🧠 Summary:\n${summary}`;
        setInput(display.slice(0, 4000));
      } catch (jsonError) {
        console.error("❌ Failed to parse JSON response:", jsonError);
        setInput(
          `📎 Uploaded: ${
            file.name || "Unknown file"
          }\n\n⚠️ Error: Invalid JSON response from server.`
        );
      }
    } catch (err) {
      console.error("❌ Upload failed:", err);
      setInput(
        `📎 Uploaded: ${
          file.name || "Unknown file"
        }\n\n⚠️ Upload failed. Check your internet connection or try a different file.`
      );
    }
  };

  const renderSupplementary = (type: "youtube" | "web", data?: any[]) => {
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
  };

  return (
    <div className="flex flex-col h-screen bg-gray-50">
      <HeaderControls
        showPromptPicker={showPromptPicker}
        setShowPromptPicker={setShowPromptPicker}
      />
      <PromptSection
        visible={showPromptPicker}
        onPromptReady={handlePromptInject}
      />

      <main className="flex-1 overflow-y-auto px-4 py-4 space-y-6">
        <RoleSelector
          selectedRole={selectedRoleId}
          onChange={setSelectedRoleId}
        />
        <ChatArea />
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
