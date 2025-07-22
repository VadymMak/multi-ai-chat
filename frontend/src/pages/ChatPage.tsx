// src/pages/ChatPage.tsx
import React, {
  useEffect,
  useRef,
  useState,
  useCallback,
  lazy,
  Suspense,
} from "react";
import { v4 as uuidv4 } from "uuid";
import { useModelStore, ModelProvider } from "../store/modelStore";
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
  getLastSessionByRole,
  getChatHistory,
} from "../services/aiApi";
import { renderSupplementary } from "../utils/renderSupplementary";
import type { Sender } from "../types/chat";
import type { RenderKind, RenderMeta } from "../types/chat";
import { getKnownRoles } from "../constants/roles";
import { createSimplePdf } from "../utils/createPdf";

const ChatHistoryPanel = lazy(
  () => import("../components/Chat/ChatHistoryPanel")
);
const ChatArea = lazy(() => import("../components/Chat/ChatArea"));
const InputBar = lazy(() => import("../components/Chat/InputBar"));
const HeaderControls = lazy(() => import("../components/Chat/HeaderControls"));
const TabbedPanel = lazy(() => import("../components/Chat/TabbedPanel"));
const AuditLogsPanel = lazy(() => import("../components/Chat/AuditLogsPanel"));
const SessionControls = lazy(
  () => import("../components/Chat/SessionControls")
);

const knownRoles = getKnownRoles();

const wantsSummaryPdf = (s: string) =>
  /\bpdf\b/i.test(s) &&
  /\bsummary|summarise|summarize|summarization|summarisation\b/i.test(s);

const parsePdfCommand = (raw: string): string[] | null => {
  const trimmed = raw.trim();
  if (!trimmed.startsWith("/pdf")) return null;
  const body = trimmed.replace(/^\/pdf\b/, "").trim();
  if (!body) return null;
  const parts = body.includes("|") ? body.split("|") : body.split(/\r?\n/);
  return parts.map((p) => p.trim()).filter(Boolean);
};

const parseRenderOverride = (
  raw: string
): { clean: string; kind?: RenderKind } => {
  let s = raw.trimStart();
  const slash = s.match(
    /^\/(plain|md|markdown|code|poem|poem_plain|poem_code)\b\s*/i
  );
  if (slash) {
    const cmd = slash[1].toLowerCase();
    s = s.slice(slash[0].length);
    let kind: RenderKind | undefined;
    if (cmd === "plain") kind = "plain";
    else if (cmd === "md" || cmd === "markdown") kind = "markdown";
    else if (cmd === "code") kind = "code";
    else if (cmd === "poem" || cmd === "poem_plain") kind = "poem_plain";
    else if (cmd === "poem_code") kind = "poem_code";
    return { clean: s.trim(), kind };
  }
  const prefix = s.match(
    /^(plain|md|markdown|code|poem|poem_plain|poem_code)\s*:\s*/i
  );
  if (prefix) {
    const head = prefix[1].toLowerCase();
    s = s.slice(prefix[0].length);
    let kind: RenderKind | undefined;
    if (head === "plain") kind = "plain";
    else if (head === "md" || head === "markdown") kind = "markdown";
    else if (head === "code") kind = "code";
    else if (head === "poem" || head === "poem_plain") kind = "poem_plain";
    else if (head === "poem_code") kind = "poem_code";
    return { clean: s.trim(), kind };
  }
  return { clean: raw.trim() };
};

// --- simple link extraction helpers (markdown + bare) ---
const MD_LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/gi;
const BARE_URL_RE = /(https?:\/\/[^\s)]+)/gi;

function extractLinks(text: string) {
  const seen = new Set<string>();
  const items: { title: string; url: string }[] = [];
  let m: RegExpExecArray | null;

  while ((m = MD_LINK_RE.exec(text))) {
    const title = (m[1] || "").trim();
    const url = (m[2] || "").trim();
    if (url && !seen.has(url)) {
      seen.add(url);
      items.push({ title: title || url, url });
    }
  }
  while ((m = BARE_URL_RE.exec(text))) {
    const url = (m[1] || "").trim();
    if (url && !seen.has(url)) {
      seen.add(url);
      items.push({ title: url, url });
    }
  }
  return items;
}

const isYouTube = (u: string) => /(?:youtube\.com|youtu\.be)/i.test(u);

const ChatPage: React.FC = () => {
  const [input, setInput] = useState("");
  const [activeTab, setActiveTab] = useState<"prompt" | "history" | "audit">(
    "history"
  );

  const inputWrapRef = useRef<HTMLDivElement>(null);
  const [inputHeight, setInputHeight] = useState<number>(84);

  const abortRef = useRef<AbortController | null>(null);
  const provider = useModelStore((s) => s.provider) as ModelProvider;

  const role = useMemoryStore((s) => s.role);
  const hasHydrated = useMemoryStore((s) => s.hasHydrated);
  const projectId = useProjectStore((s) => s.projectId ?? null);

  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const addMessage = useChatStore((s) => s.addMessage);
  const setTyping = useChatStore((s) => s.setTyping);

  const { isLoading } = useAppStore();
  const streamText = useStreamText();
  const roleId = typeof role?.id === "number" ? role.id : null;
  const hasRestoredRole = useRef(false);

  // Observe InputBar wrapper height (throttled via rAF)
  useEffect(() => {
    const el = inputWrapRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    let raf: number | null = null;

    const ro = new ResizeObserver((entries) => {
      const last = entries[entries.length - 1];
      const h = Math.ceil(last.contentRect.height);
      if (raf != null) cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        setInputHeight((prev) => (prev !== h ? h : prev));
      });
    });

    ro.observe(el);
    // initial measure
    try {
      const h0 = Math.ceil(el.getBoundingClientRect().height);
      setInputHeight((prev) => (prev !== h0 ? h0 : prev));
    } catch {}

    return () => {
      try {
        ro.disconnect();
      } catch {}
      if (raf != null) cancelAnimationFrame(raf);
    };
  }, []);

  // Abort any in-flight stream on unmount
  useEffect(() => {
    return () => {
      try {
        abortRef.current?.abort();
        abortRef.current = null;
      } catch {}
    };
  }, []);

  // Try to map backend role_name → knownRoles only once
  useEffect(() => {
    const restoreLastSession = async () => {
      if (hasRestoredRole.current || !hasHydrated) return;
      if (!role && roleId && projectId) {
        try {
          const res = await getLastSessionByRole(roleId, projectId);
          if (res?.role_id && res?.role_name) {
            const matched = knownRoles.find(
              (r) => r.id === res.role_id && r.name === res.role_name
            );
            if (matched) {
              hasRestoredRole.current = true;
              useMemoryStore.getState().setRole(matched);
            }
          }
        } catch (err) {
          console.warn("⚠️ Could not restore role from backend:", err);
        }
      }
    };
    restoreLastSession();
  }, [hasHydrated, role, roleId, projectId]);

  // Bootstrap or restore chat session
  useEffect(() => {
    if (!hasHydrated) return;
    const store = useChatStore.getState();
    if (store.sessionReady) return;

    if (store.lastSessionMarker) {
      store.restoreSessionFromMarker().then((ok) => {
        if (!ok && roleId && projectId) {
          store.loadOrInitSessionForRoleProject(roleId, Number(projectId));
        }
      });
      return;
    }

    if (roleId && projectId) {
      store.loadOrInitSessionForRoleProject(roleId, Number(projectId));
    }
  }, [hasHydrated, roleId, projectId]);

  useSessionCleanup();

  // HYDRATE HISTORY once per (roleId, projectId, chatSessionId)
  useEffect(() => {
    const store = useChatStore.getState();
    if (!roleId || !projectId || !chatSessionId || !store.sessionReady) return;

    const alreadyHas = store.messages?.some(
      (m) =>
        String(m.project_id) === String(projectId) &&
        String(m.chat_session_id) === String(chatSessionId) &&
        Number(m.role_id) === Number(roleId)
    );
    if (alreadyHas) return;

    (async () => {
      try {
        const { messages } = await getChatHistory(
          projectId,
          roleId,
          chatSessionId
        );
        if (messages.length && typeof store.addMessage === "function") {
          messages.forEach((m) => store.addMessage(m));
        }
      } catch (e) {
        console.error("⚠️ Failed to load chat history:", e);
      }
    })();
  }, [roleId, projectId, chatSessionId]);

  const ensureSessionId = useCallback(
    async (rid: number, pid: number): Promise<string | null> => {
      let sid = useChatStore.getState().chatSessionId;
      if (sid) return sid;
      try {
        sid = await useChatStore.getState().waitForSessionReady(rid, pid, 5000);
        return sid;
      } catch (e) {
        console.warn("⚠️ Session not ready in time:", e);
        return null;
      }
    },
    []
  );

  // ⬇️ accepts overrides and prefers overrides.kind over parsed slash/prefix
  const handleSend = useCallback(
    async (
      text?: string,
      overrides?: {
        kind?: RenderKind;
        language?: string | null;
        filename?: string | null;
      }
    ) => {
      const raw = (text ?? input).trim();
      if (!raw || !roleId || !projectId) return;

      const { clean, kind: parsedKind } = parseRenderOverride(raw);
      const selectedKind = overrides?.kind ?? parsedKind;
      const messageToSend = clean;

      const sid =
        chatSessionId || (await ensureSessionId(roleId, Number(projectId)));
      if (!sid) {
        console.warn("⚠️ No chatSessionId — cannot send message.");
        return;
      }

      // PDF command mode
      const pdfLines = parsePdfCommand(messageToSend);
      if (pdfLines && pdfLines.length) {
        setTyping(true);
        abortRef.current?.abort();
        abortRef.current = new AbortController();

        const userMessage = {
          id: `user-${uuidv4()}`,
          sender: "user" as Sender,
          text: raw,
          role_id: roleId,
          project_id: projectId,
          chat_session_id: sid,
        };
        addMessage(userMessage);
        setInput("");

        try {
          const { url, filename } = await createSimplePdf(pdfLines, {
            title: "Export",
            filename: "chat-output",
          });
          addMessage({
            id: `ai-${uuidv4()}`,
            sender: "openai",
            text: "📄 Here is your PDF export.",
            role_id: roleId,
            project_id: projectId,
            chat_session_id: sid,
            attachments: [
              {
                id: `att-${uuidv4()}`,
                name: filename,
                mime: "application/pdf",
                url,
              },
            ],
          });
        } catch (err) {
          console.error("❌ PDF creation failed:", err);
          addMessage({
            id: `ai-${uuidv4()}`,
            sender: "openai",
            text: "⚠️ Failed to create PDF.",
            role_id: roleId,
            project_id: projectId,
            chat_session_id: sid,
          });
        } finally {
          setTyping(false);
        }
        return;
      }

      const wantsPdf = wantsSummaryPdf(messageToSend);

      setTyping(true);
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      // Add user bubble
      const userMessage = {
        id: `user-${uuidv4()}`,
        sender: "user" as Sender,
        text: messageToSend,
        role_id: roleId,
        project_id: projectId,
        chat_session_id: sid,
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
            sid
          );

          let collected = "";
          let starterTextForLinks: string | null = null;

          let idx = -1;
          for (const { sender, text, isSummary } of result.messages) {
            idx++;
            const msgId = `${sender}-${uuidv4()}`;
            addMessage({
              id: msgId,
              sender: sender as Sender,
              text: "",
              isTyping: true,
              isSummary,
              role_id: roleId,
              project_id: projectId,
              chat_session_id: sid,
            });
            const chunkText = text || "⚠️ Empty";
            await streamText(msgId, chunkText, abortRef.current?.signal);

            if (idx === 0) starterTextForLinks = chunkText;

            const s = String(sender);
            if (s !== "web" && s !== "youtube") {
              collected += (collected ? "\n\n" : "") + chunkText;
            }
          }

          if (result.youtube?.length) {
            await renderSupplementary(
              "youtube",
              result.youtube,
              addMessage,
              streamText,
              abortRef.current?.signal,
              roleId,
              projectId,
              sid
            );
          } else if (starterTextForLinks) {
            const links = extractLinks(starterTextForLinks)
              .filter((x) => isYouTube(x.url))
              .slice(0, 6);
            if (links.length) {
              await renderSupplementary(
                "youtube",
                links,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }
          }

          if (result.web?.length) {
            await renderSupplementary(
              "web",
              result.web,
              addMessage,
              streamText,
              abortRef.current?.signal,
              roleId,
              projectId,
              sid
            );
          } else if (starterTextForLinks) {
            const links = extractLinks(starterTextForLinks)
              .filter((x) => !isYouTube(x.url))
              .slice(0, 6);
            if (links.length) {
              await renderSupplementary(
                "web",
                links,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }
          }

          const returnedSid = (result as any)?.chat_session_id as
            | string
            | undefined;
          if (returnedSid) {
            useChatStore.getState().handleSessionIdUpdateFromAsk(returnedSid);
          }

          if (wantsPdf && collected.trim()) {
            try {
              const lines = collected.split(/\r?\n/).filter((l) => l.trim());
              const { url, filename } = await createSimplePdf(lines, {
                title: "Summary",
                filename: `summary-${sid.slice(0, 8)}`,
              });
              addMessage({
                id: `ai-${uuidv4()}`,
                sender: "openai",
                text: "📄 Summary exported as PDF.",
                role_id: roleId,
                project_id: projectId,
                chat_session_id: sid,
                attachments: [
                  {
                    id: `att-${uuidv4()}`,
                    name: filename,
                    mime: "application/pdf",
                    url,
                  },
                ],
              });
            } catch (err) {
              console.error("❌ PDF export failed:", err);
            }
          }
        } else {
          // /ask
          const result = await sendAiMessage(
            messageToSend,
            provider as "openai" | "anthropic" | "all",
            roleId,
            projectId,
            sid,
            selectedKind
              ? {
                  kind: selectedKind,
                  language:
                    overrides && "language" in overrides
                      ? overrides.language ?? undefined
                      : undefined,
                  filename:
                    overrides && "filename" in overrides
                      ? overrides.filename ?? undefined
                      : undefined,
                }
              : undefined
          );

          if (result?.chat_session_id) {
            useChatStore
              .getState()
              .handleSessionIdUpdateFromAsk(result.chat_session_id);
          }

          if (provider === "all") {
            let collected = "";
            const topSources = (result as any)?.sources;

            for (const m of result.messages) {
              const id = `ai-${uuidv4()}`;
              const sender = (m.sender as Sender) || "openai";
              const textOut = String(m.text ?? "");
              const renderMeta = (m as any)?.render as RenderMeta | undefined;

              addMessage({
                id,
                sender,
                text: "",
                isTyping: true,
                role_id: roleId,
                project_id: projectId,
                chat_session_id: sid,
                ...(renderMeta ? ({ render: renderMeta } as any) : {}),
              });

              await streamText(
                id,
                textOut || "🤖 No response",
                abortRef.current?.signal
              );

              if (sender !== "web" && sender !== "youtube") {
                collected += (collected ? "\n\n" : "") + (textOut || "");
              }
            }

            if (topSources?.youtube?.length) {
              await renderSupplementary(
                "youtube",
                topSources.youtube,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }
            if (topSources?.web?.length) {
              await renderSupplementary(
                "web",
                topSources.web,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }

            if (wantsPdf && collected.trim()) {
              try {
                const lines = collected.split(/\r?\n/).filter((l) => l.trim());
                const { url, filename } = await createSimplePdf(lines, {
                  title: "Summary",
                  filename: `summary-${sid.slice(0, 8)}`,
                });
                addMessage({
                  id: `ai-${uuidv4()}`,
                  sender: "openai",
                  text: "📄 Summary exported as PDF.",
                  role_id: roleId,
                  project_id: projectId,
                  chat_session_id: sid,
                  attachments: [
                    {
                      id: `att-${uuidv4()}`,
                      name: filename,
                      mime: "application/pdf",
                      url,
                    },
                  ],
                });
              } catch (err) {
                console.error("❌ PDF export failed:", err);
              }
            }
          } else {
            // SINGLE MODEL
            const sources =
              (result as any)?.sources ??
              (result?.messages?.[0] as any)?.sources ??
              undefined;

            const renderMeta =
              ((result?.messages?.[0] as any)?.render as
                | RenderMeta
                | undefined) ?? undefined;

            const id = `ai-${uuidv4()}`;
            addMessage({
              id,
              sender: provider as Sender,
              text: "",
              isTyping: true,
              role_id: roleId,
              project_id: projectId,
              chat_session_id: sid,
              ...(renderMeta ? ({ render: renderMeta } as any) : {}),
            });

            const aiText = result.messages[0]?.text || "🤖 No response";
            await streamText(id, aiText, abortRef.current?.signal);

            if (sources?.youtube?.length) {
              await renderSupplementary(
                "youtube",
                sources.youtube,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }
            if (sources?.web?.length) {
              await renderSupplementary(
                "web",
                sources.web,
                addMessage,
                streamText,
                abortRef.current?.signal,
                roleId,
                projectId,
                sid
              );
            }

            if (wantsPdf && aiText.trim()) {
              try {
                const lines = aiText.split(/\r?\n/).filter((l) => l.trim());
                const { url, filename } = await createSimplePdf(lines, {
                  title: "Summary",
                  filename: `summary-${sid.slice(0, 8)}`,
                });
                addMessage({
                  id: `ai-${uuidv4()}`,
                  sender: "openai",
                  text: "📄 Summary exported as PDF.",
                  role_id: roleId,
                  project_id: projectId,
                  chat_session_id: sid,
                  attachments: [
                    {
                      id: `att-${uuidv4()}`,
                      name: filename,
                      mime: "application/pdf",
                      url,
                    },
                  ],
                });
              } catch (err) {
                console.error("❌ PDF export failed:", err);
              }
            }
          }
        }
      } catch (err) {
        console.error("❌ Send failed:", err);
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
      addMessage,
      streamText,
      setTyping,
      ensureSessionId,
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

  // Upload → post a small SYSTEM message only. No auto-summarize.
  const handleFileDrop = useCallback(
    async (file: File): Promise<string | null> => {
      if (!roleId || !projectId) return null;

      const sid =
        chatSessionId || (await ensureSessionId(roleId, Number(projectId)));
      if (!sid) return null;

      try {
        await uploadFile(file, roleId, projectId, sid);

        addMessage({
          id: `sys-${uuidv4()}`,
          sender: "system" as Sender,
          text:
            `📎 Uploaded “${file.name}”. File is attached to this session and ready.\n\n` +
            `Tip: ask “summarize the uploaded file” or “extract key points”.`,
          role_id: roleId,
          project_id: projectId,
          chat_session_id: sid,
        });

        return null; // never auto-send
      } catch (err) {
        console.error("❌ Upload failed:", err);
        addMessage({
          id: `sys-${uuidv4()}`,
          sender: "system" as Sender,
          text: `⚠️ Upload failed for “${file.name}”. Please try again.`,
          role_id: roleId,
          project_id: projectId,
          chat_session_id: sid,
        });
        return null;
      }
    },
    [addMessage, roleId, projectId, chatSessionId, ensureSessionId]
  );

  return (
    <>
      {isLoading && <LoadingOverlay />}
      <div className="flex flex-col h-screen overflow-hidden">
        {/* App Header */}
        <div className="sticky top-0 z-10 bg-white border-b shadow-sm">
          <Suspense
            fallback={
              <div className="p-2 text-sm text-gray-400">Loading header…</div>
            }
          >
            <HeaderControls />
          </Suspense>
        </div>

        {/* Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <aside className="w-72 flex-shrink-0 border-r bg-gray-50 flex flex-col h-full">
            <div className="sticky top-0 z-10 bg-gray-50/95 backdrop-blur border-b">
              <div className="p-3">
                <div className="flex flex-col space-y-2 text-sm">
                  {(["history", "prompt", "audit"] as const).map((tab) => (
                    <button
                      key={tab}
                      className={`text-left p-2 rounded ${
                        activeTab === tab ? "bg-blue-100 font-semibold" : ""
                      }`}
                      onClick={() => setActiveTab(tab)}
                    >
                      {tab === "history" && "📜 History"}
                      {tab === "prompt" && "🧠 Prompt Library"}
                      {tab === "audit" && "🗂️ Audit Logs"}
                    </button>
                  ))}
                </div>

                <div className="mt-4">
                  <Suspense
                    fallback={
                      <div className="text-xs text-gray-400">
                        Loading sessions…
                      </div>
                    }
                  >
                    <SessionControls />
                  </Suspense>
                </div>
              </div>
            </div>

            {/* Single scroll owner for panel content */}
            <div className="flex-1 min-h-0 overflow-y-auto p-3">
              <div className="min-w-0">
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
          </aside>

          {/* Main Chat */}
          <div className="flex flex-col flex-1 min-w-0">
            <div className="flex-1 min-h-0">
              <Suspense
                fallback={
                  <div className="p-4 text-sm text-gray-400">Loading chat…</div>
                }
              >
                <ChatArea bottomPad={inputHeight} />
              </Suspense>
            </div>

            {/* InputBar */}
            <div ref={inputWrapRef} className="border-t p-3 bg-white shrink-0">
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

        <footer className="text-center text-xs text-gray-500 py-2 border-t bg-white">
          © {new Date().getFullYear()} Your AI Assistant • Built with React +
          FastAPI
        </footer>
      </div>
    </>
  );
};

export default ChatPage;
