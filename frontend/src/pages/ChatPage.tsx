// ChatPage.tsx (✅ updated for proper chat history restore)
import React, {
  useEffect,
  useRef,
  useState,
  useCallback,
  useMemo,
  lazy,
  Suspense,
} from "react";
import { v4 as uuidv4 } from "uuid";
import { useModelStore } from "../store/modelStore";
import { useChatStore } from "../store/chatStore";
import { useProjectStore } from "../store/projectStore";
import { useMemoryStore } from "../store/memoryStore";
import { useStreamText } from "../hooks/useStreamText";
import { useSessionCleanup } from "../hooks/useSessionCleanup";
import { useAppStore } from "../store/appStore";
import LoadingOverlay from "../components/Shared/LoadingOverlay";
import {
  sendAiMessage,
  sendAiToAiMessage,
  uploadFile,
  getChatHistory,
} from "../services/aiApi";
import { renderSupplementary } from "../utils/renderSupplementary";
import type { Sender } from "../types/chat";

const ChatHistoryPanel = lazy(
  () => import("../components/Chat/ChatHistoryPanel")
);
const ChatArea = lazy(() => import("../components/Chat/ChatArea"));
const InputBar = lazy(() => import("../components/Chat/InputBar"));
const HeaderControls = lazy(() => import("../components/Chat/HeaderControls"));
const TabbedPanel = lazy(() => import("../components/Chat/TabbedPanel"));
const AuditLogsPanel = lazy(() => import("../components/Chat/AuditLogsPanel"));

const ChatPage: React.FC = () => {
  const [input, setInput] = useState("");
  const [activeTab, setActiveTab] = useState<"prompt" | "history" | "audit">(
    "history"
  );
  const abortRef = useRef<AbortController | null>(null);
  const hasFetchedHistory = useRef(false);

  const initializeChatSession = useChatStore((s) => s.initializeChatSession);
  const provider = useModelStore((s) => s.provider);
  const role = useMemoryStore((s) => s.role);
  const projectId = useProjectStore((s) => s.projectId ?? 1);
  const chatSessionId = useChatStore((s) => s.chatSessionId ?? undefined);
  const addMessage = useChatStore((s) => s.addMessage);
  const setMessages = useChatStore((s) => s.setMessages);
  const setLastSessionMarker = useChatStore((s) => s.setLastSessionMarker);
  const setTyping = useChatStore((s) => s.setTyping);
  const streamText = useStreamText();
  const isLoading = useAppStore((s) => s.isLoading);
  const setLoading = useAppStore((s) => s.setLoading);

  const roleId = useMemo(
    () => (typeof role?.id === "number" ? role.id : null),
    [role]
  );

  useEffect(() => {
    initializeChatSession(); // ensures chat_session_id is set if not present
  }, [initializeChatSession]);

  useSessionCleanup();

  useEffect(() => {
    const loadChatHistory = async () => {
      if (!roleId || !chatSessionId || hasFetchedHistory.current) return;
      try {
        setLoading(true);
        const history = await getChatHistory(projectId, roleId, chatSessionId);
        if (Array.isArray(history?.messages)) {
          setMessages(history.messages);
          setLastSessionMarker({ projectId, roleId, chatSessionId });
          hasFetchedHistory.current = true;
        }
      } catch (err) {
        console.error("❌ Failed to load chat history:", err);
      } finally {
        setLoading(false);
      }
    };

    loadChatHistory();
  }, [
    projectId,
    roleId,
    chatSessionId,
    setMessages,
    setLastSessionMarker,
    setLoading,
  ]);

  const handleSend = useCallback(
    async (text?: string) => {
      const messageToSend = (text ?? input).trim();
      if (!messageToSend || !roleId) return;

      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      const userMessage = {
        id: `user-${uuidv4()}`,
        sender: "user" as Sender,
        text: messageToSend,
        role_id: roleId,
        project_id: projectId,
        chat_session_id: chatSessionId,
      };
      addMessage(userMessage);
      setInput("");

      try {
        if (provider === "boost") {
          const result = await sendAiToAiMessage(
            messageToSend,
            "openai",
            roleId,
            projectId,
            chatSessionId
          );
          for (const { sender, text, isSummary } of result.messages) {
            const msgId = `${sender}-${uuidv4()}`;
            addMessage({
              id: msgId,
              sender: sender as Sender,
              text: "",
              isTyping: true,
              isSummary,
              role_id: roleId,
              project_id: projectId,
              chat_session_id: chatSessionId,
            });
            await streamText(
              msgId,
              text || "⚠️ Empty",
              abortRef.current?.signal
            );
          }

          if (result.youtube) {
            await renderSupplementary(
              "youtube",
              result.youtube,
              addMessage,
              streamText,
              abortRef.current?.signal,
              roleId,
              projectId,
              chatSessionId
            );
          }
          if (result.web) {
            await renderSupplementary(
              "web",
              result.web,
              addMessage,
              streamText,
              abortRef.current?.signal,
              roleId,
              projectId,
              chatSessionId
            );
          }
        } else {
          const typedProvider = provider as "openai" | "anthropic" | "all";
          const result = await sendAiMessage(
            messageToSend,
            typedProvider,
            roleId,
            projectId,
            chatSessionId
          );
          const id = `ai-${uuidv4()}`;
          addMessage({
            id,
            sender: typedProvider === "all" ? "openai" : typedProvider,
            text: "",
            isTyping: true,
            role_id: roleId,
            project_id: projectId,
            chat_session_id: chatSessionId,
          });
          await streamText(
            id,
            result.messages[1]?.text || "🤖 No response",
            abortRef.current?.signal
          );
        }
      } catch (err) {
        console.error("❌ send failed:", err);
      } finally {
        setTyping(false);
      }
    },
    [
      input,
      provider,
      roleId,
      projectId,
      chatSessionId,
      setTyping,
      addMessage,
      streamText,
    ]
  );

  const handlePromptReady = useCallback(
    (prompt: string) => setInput(prompt),
    []
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

  const handleFileDrop = useCallback(
    async (file: File): Promise<string | null> => {
      if (!roleId) return null;
      try {
        const result = await uploadFile(file, roleId, projectId, chatSessionId);
        if (result?.summary) {
          await handleSend(result.summary);
          return result.summary;
        }
        return null;
      } catch (err) {
        console.error("❌ File upload failed:", err);
        return null;
      }
    },
    [handleSend, roleId, projectId, chatSessionId]
  );

  return (
    <>
      {isLoading && <LoadingOverlay />}
      <div className="flex flex-col h-screen overflow-hidden">
        {/* Header */}
        <div className="h-auto sticky top-0 z-10 bg-white border-b shadow-sm px-4 py-2">
          <Suspense
            fallback={
              <div className="text-sm text-gray-400">Loading header…</div>
            }
          >
            <HeaderControls />
          </Suspense>
        </div>

        {/* Main Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <div className="w-64 flex-shrink-0 border-r bg-gray-50 flex flex-col h-full">
            <div className="p-3 overflow-y-auto flex-1">
              <div className="flex flex-col space-y-2 text-sm">
                {["history", "prompt", "audit"].map((tab) => (
                  <button
                    key={tab}
                    className={`text-left p-2 rounded ${
                      activeTab === tab ? "bg-blue-100 font-semibold" : ""
                    }`}
                    onClick={() => setActiveTab(tab as any)}
                  >
                    {tab === "history" && "📜 History"}
                    {tab === "prompt" && "🧠 Prompt Library"}
                    {tab === "audit" && "🗂️ Audit Logs"}
                  </button>
                ))}
              </div>

              <div className="mt-4">
                {activeTab === "history" && (
                  <Suspense fallback={<div>Loading history…</div>}>
                    <ChatHistoryPanel />
                  </Suspense>
                )}
                {activeTab === "prompt" && (
                  <Suspense fallback={<div>Loading prompts…</div>}>
                    <TabbedPanel onPromptReady={handlePromptReady} />
                  </Suspense>
                )}
                {activeTab === "audit" && (
                  <Suspense
                    fallback={
                      <div className="text-xs text-gray-400">
                        Loading audit logs…
                      </div>
                    }
                  >
                    <AuditLogsPanel />
                  </Suspense>
                )}
              </div>
            </div>
            <div className="h-[84px] bg-gray-50" />
          </div>

          {/* Chat column */}
          <div className="flex flex-col flex-1 overflow-hidden">
            <div className="flex-1 overflow-y-auto">
              <Suspense
                fallback={
                  <div className="p-4 text-sm text-gray-400">Loading chat…</div>
                }
              >
                <ChatArea />
              </Suspense>
            </div>
            <div className="border-t p-3 bg-white shrink-0">
              <Suspense
                fallback={
                  <div className="p-2 text-sm text-gray-400">
                    Loading input…
                  </div>
                }
              >
                <InputBar
                  input={input}
                  setInput={setInput}
                  handleSend={handleSend}
                  handleKeyDown={handleKeyDown}
                  abortRef={abortRef}
                  onFileDrop={handleFileDrop}
                />
              </Suspense>
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs text-gray-500 py-2 border-t bg-white">
          © {new Date().getFullYear()} Your AI Assistant • Built with React +
          FastAPI
        </footer>
      </div>
    </>
  );
};

export default ChatPage;
