// File: src/components/Chat/InputBar.tsx
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  useMemo,
} from "react";
import { useDropzone } from "react-dropzone";
import { Paperclip } from "lucide-react";

import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import type { RenderKind } from "../../types/chat";

type OutputMode = "plain" | "doc" | "code";
type Presentation = "default" | "poem_plain" | "poem_code";

interface InputOverrides {
  kind?: RenderKind;
  language?: string | null;
  filename?: string | null;
}

interface InputBarProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: (
    text?: string,
    overrides?: InputOverrides
  ) => void | Promise<void>;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAbortTyping?: () => void;
  onFileDrop: (file: File) => Promise<string | null>;
  abortRef?: React.RefObject<AbortController | null>;
}

const MAX_TEXTAREA_PX = 240;

const InputBar: React.FC<InputBarProps> = ({
  input,
  setInput,
  handleSend,
  handleKeyDown,
  onAbortTyping,
  onFileDrop,
  abortRef,
}) => {
  const roleId = useMemoryStore((s) => s.role?.id ?? null);
  const projectId = useProjectStore((s) => s.projectId);
  const sessionReady = useChatStore((s) => s.sessionReady);
  const waitingSession = !sessionReady;

  // Local composer state (decoupled from parent)
  const [text, setText] = useState<string>(input ?? "");
  useEffect(() => {
    if (input !== text) setText(input ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);

  // Output mode
  const [mode, setMode] = useState<OutputMode>("doc");
  const [presentation, setPresentation] = useState<Presentation>("default");

  const containerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sendingRef = useRef(false); // re-entrancy guard
  const [isSending, setIsSending] = useState(false); // reflect in UI
  const composingRef = useRef(false); // IME composition guard

  // Auto-grow
  const autosize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(el.scrollHeight, MAX_TEXTAREA_PX);
    el.style.height = `${next}px`;
  }, []);
  useLayoutEffect(() => {
    autosize();
  }, [autosize, text]);
  useEffect(() => {
    autosize();
  }, [autosize]);

  // Map UI → RenderKind
  const toRenderKind = useCallback(
    (m: OutputMode, p: Presentation): RenderKind => {
      if (m === "code" && p === "poem_code") return "poem_code";
      if (m === "plain" && p === "poem_plain") return "poem_plain";
      if (m === "code") return "code";
      if (m === "plain") return "plain";
      return "markdown";
    },
    []
  );

  const currentOverrides = useMemo<InputOverrides>(
    () => ({ kind: toRenderKind(mode, presentation) }),
    [mode, presentation, toRenderKind]
  );

  // Common send action — clear immediately, then await
  const sendCurrent = useCallback(async () => {
    if (sendingRef.current) return; // prevent double send
    if (composingRef.current) return; // don't send mid-IME
    if (waitingSession) return;

    const value = text.trim();
    if (!value || !roleId || !projectId) return;

    sendingRef.current = true;
    setIsSending(true);

    // Clear synchronously for instant UX
    setText("");
    setInput("");
    requestAnimationFrame(() => autosize());

    try {
      await handleSend(value, currentOverrides);
    } finally {
      sendingRef.current = false;
      setIsSending(false);
    }
  }, [
    waitingSession,
    text,
    roleId,
    projectId,
    handleSend,
    currentOverrides,
    setInput,
    autosize,
  ]);

  // ---- File drop/paste: upload only; DO NOT auto-send anything ----
  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (waitingSession) return;
      if (acceptedFiles.length > 0 && roleId && projectId) {
        await onFileDrop(acceptedFiles[0]);
        // keep any typed text; just fix textarea height
        requestAnimationFrame(() => autosize());
      }
    },
    [waitingSession, roleId, projectId, onFileDrop, autosize]
  );

  const { getRootProps, getInputProps, open } = useDropzone({
    onDrop,
    noClick: true,
    multiple: false,
    accept: {
      "application/pdf": [".pdf"],
      "text/plain": [".txt", ".log", ".md"],
      "application/json": [".json"],
      "text/csv": [".csv"],
      "image/*": [".png", ".jpg", ".jpeg", ".webp"],
    },
    disabled: waitingSession || isSending, // only disabled while sending a prompt
  });

  const onPaste = useCallback(
    async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (waitingSession) return;

      const files = e.clipboardData?.files;
      let file: File | null = null;

      if (files && files.length > 0) {
        file = files[0];
      } else if (e.clipboardData?.items?.length) {
        const item = Array.from(e.clipboardData.items).find(
          (it) => it.kind === "file"
        );
        file = item?.getAsFile() ?? null;
      }

      if (file && roleId && projectId) {
        e.preventDefault();
        await onFileDrop(file);
        requestAnimationFrame(() => autosize());
      }
      // if no file, fall through to normal text paste
    },
    [waitingSession, roleId, projectId, onFileDrop, autosize]
  );

  // Submit (non-blocking)
  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      void sendCurrent();
    },
    [sendCurrent]
  );

  // Keyboard: Enter=send (no shift), Ctrl/Cmd+Enter=send (skip when composing)
  const onKeyDownLocal = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const isEnter = e.key === "Enter";
      const sendCombo = (e.ctrlKey || e.metaKey) && isEnter;
      const plainEnterSend = isEnter && !e.shiftKey;

      if (
        !waitingSession &&
        !isSending &&
        !composingRef.current &&
        (sendCombo || plainEnterSend)
      ) {
        e.preventDefault();
        e.stopPropagation();
        void sendCurrent();
        return;
      }
      handleKeyDown(e);
    },
    [waitingSession, isSending, sendCurrent, handleKeyDown]
  );

  // IME composition flags
  const onCompositionStart = () => (composingRef.current = true);
  const onCompositionEnd = () => (composingRef.current = false);

  // Abort streaming
  const handleAbort = useCallback(() => {
    if (abortRef?.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    onAbortTyping?.();
  }, [abortRef, onAbortTyping]);

  const canSend =
    !waitingSession && !isSending && !!text.trim() && !!roleId && !!projectId;

  // Mode toggles
  const setPlain = () => {
    setMode("plain");
    setPresentation("default");
  };
  const setMarkdown = () => {
    setMode("doc");
    setPresentation("default");
  };
  const setCode = () => {
    setMode("code");
    setPresentation("default");
  };
  const setPoemPlain = () => {
    setMode("plain");
    setPresentation("poem_plain");
  };
  const setPoemCode = () => {
    setMode("code");
    setPresentation("poem_code");
  };

  const btnBase = "px-2 py-1 rounded text-xs border transition";
  const btnActive = "bg-blue-600 text-white border-blue-600";
  const btnIdle = "hover:bg-gray-100";

  return (
    <form onSubmit={handleSubmit} className="w-full" aria-busy={isSending}>
      <label htmlFor="chat-input" className="mb-1 block text-xs text-gray-500">
        💬 Ask something to your selected AI
      </label>

      <div
        {...getRootProps()}
        ref={containerRef}
        className={`relative flex gap-2 items-end border border-gray-300 rounded-lg px-3 py-2 shadow-sm bg-white focus-within:ring-2 focus-within:ring-blue-500 ${
          waitingSession || isSending ? "opacity-50 pointer-events-none" : ""
        }`}
      >
        <textarea
          id="chat-input"
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={onKeyDownLocal}
          onCompositionStart={onCompositionStart}
          onCompositionEnd={onCompositionEnd}
          onPaste={onPaste}
          placeholder={
            waitingSession
              ? "⏳ Initializing session… please wait"
              : "Ask something... or drop/paste a file"
          }
          rows={1}
          disabled={waitingSession}
          data-gramm="false"
          aria-disabled={waitingSession}
          className="flex-1 resize-none outline-none text-sm max-h-[240px] overflow-y-auto placeholder:text-gray-400 leading-snug disabled:opacity-50"
        />

        {/* Hidden input for dropzone */}
        <input {...getInputProps()} />

        {/* Attach / Upload */}
        <button
          type="button"
          onClick={open}
          className="text-gray-500 hover:text-blue-600 p-1"
          title="Upload file"
          aria-label="Upload file"
          disabled={waitingSession || isSending}
          aria-disabled={waitingSession || isSending}
        >
          <Paperclip size={18} />
        </button>

        {/* Actions */}
        <div className="flex flex-col gap-2 ml-2">
          {/* Output-mode toggles */}
          <div className="flex flex-wrap gap-1 justify-end">
            <button
              type="button"
              title="Plain"
              aria-label="Plain"
              aria-pressed={mode === "plain" && presentation === "default"}
              onClick={setPlain}
              className={`${btnBase} ${
                mode === "plain" && presentation === "default"
                  ? btnActive
                  : btnIdle
              }`}
            >
              Plain
            </button>
            <button
              type="button"
              title="Markdown"
              aria-label="Markdown"
              aria-pressed={mode === "doc" && presentation === "default"}
              onClick={setMarkdown}
              className={`${btnBase} ${
                mode === "doc" && presentation === "default"
                  ? btnActive
                  : btnIdle
              }`}
            >
              MD
            </button>
            <button
              type="button"
              title="Code block"
              aria-label="Code block"
              aria-pressed={mode === "code" && presentation === "default"}
              onClick={setCode}
              className={`${btnBase} font-mono ${
                mode === "code" && presentation === "default"
                  ? btnActive
                  : btnIdle
              }`}
            >
              Code
            </button>
            <button
              type="button"
              title="Poem (plain)"
              aria-label="Poem (plain)"
              aria-pressed={mode === "plain" && presentation === "poem_plain"}
              onClick={setPoemPlain}
              className={`${btnBase} ${
                mode === "plain" && presentation === "poem_plain"
                  ? btnActive
                  : btnIdle
              }`}
            >
              Poem·plain
            </button>
            <button
              type="button"
              title="Poem (code-styled)"
              aria-label="Poem (code-styled)"
              aria-pressed={mode === "code" && presentation === "poem_code"}
              onClick={setPoemCode}
              className={`${btnBase} font-mono ${
                mode === "code" && presentation === "poem_code"
                  ? btnActive
                  : btnIdle
              }`}
            >
              Poem⌁code
            </button>
          </div>

          <button
            type="submit"
            disabled={!canSend}
            aria-disabled={!canSend}
            className={`px-4 py-2 rounded-lg text-sm transition ${
              canSend
                ? "bg-blue-600 text-white hover:bg-blue-700"
                : "bg-gray-300 text-gray-600 cursor-not-allowed"
            }`}
            aria-label="Send message"
          >
            Send
          </button>

          {onAbortTyping && (
            <button
              type="button"
              onClick={handleAbort}
              className="px-4 py-2 bg-gray-200 text-red-600 hover:text-red-800 rounded-lg text-sm"
              disabled={waitingSession}
              aria-disabled={waitingSession}
              aria-label="Abort response generation"
            >
              Abort
            </button>
          )}
        </div>
      </div>
    </form>
  );
};

export default InputBar;
