// File: src/components/Chat/InputBar.tsx
import React, { useCallback, useEffect, useLayoutEffect, useRef } from "react";
import { useDropzone } from "react-dropzone";
import { Paperclip } from "lucide-react";

import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import type { RenderKind } from "../../types/chat";

interface InputBarProps {
  input: string;
  setInput: (val: string) => void;
  /**
   * Your ChatPage currently accepts only (text?: string).
   * We allow an optional overrides arg but we *don’t rely on it*;
   * we prepend the slash prefix so legacy flow keeps working.
   */
  handleSend: (
    text?: string,
    overrides?: {
      kind?: RenderKind;
      language?: string | null;
      filename?: string | null;
    }
  ) => void | Promise<void>;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAbortTyping?: () => void;
  onFileDrop: (file: File) => Promise<string | null>;
  abortRef?: React.RefObject<AbortController | null>;
}

const MAX_TEXTAREA_PX = 240; // ~12 lines depending on line-height

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

  const containerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);

  // --- Auto-grow textarea (no layout thrash) ---
  const autosize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(el.scrollHeight, MAX_TEXTAREA_PX);
    el.style.height = `${next}px`;
  }, []);

  useLayoutEffect(() => {
    autosize();
  }, [autosize, input]);

  useEffect(() => {
    autosize();
  }, [autosize]);

  // --- Dropzone: drag/drop or click paperclip to upload ---
  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (waitingSession) return;
      if (acceptedFiles.length > 0 && roleId && projectId) {
        const summary = await onFileDrop(acceptedFiles[0]);
        if (summary) {
          setInput("");
          // send as plain text (server can handle)
          handleSend(summary);
        }
      }
    },
    [onFileDrop, handleSend, setInput, roleId, projectId, waitingSession]
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
    disabled: waitingSession,
  });

  // --- Paste file directly into the textarea ---
  const onPaste = useCallback(
    async (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
      if (waitingSession) return;
      const files = e.clipboardData?.files;
      if (files && files.length > 0 && roleId && projectId) {
        e.preventDefault();
        const summary = await onFileDrop(files[0]);
        if (summary) {
          setInput("");
          handleSend(summary);
        }
      }
    },
    [waitingSession, roleId, projectId, onFileDrop, handleSend, setInput]
  );

  // --- Submit handlers ---
  const handleSubmit = useCallback(
    async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (waitingSession) return;
      const value = input.trim();
      if (value && roleId && projectId) {
        handleSend(value); // default = markdown (slash-free)
        setInput("");
      }
    },
    [handleSend, input, setInput, roleId, projectId, waitingSession]
  );

  const onKeyDownLocal = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      handleKeyDown(e);
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && !waitingSession) {
        e.preventDefault();
        const value = input.trim();
        if (value && roleId && projectId) {
          handleSend(value);
          setInput("");
        }
      }
    },
    [
      handleKeyDown,
      waitingSession,
      input,
      roleId,
      projectId,
      handleSend,
      setInput,
    ]
  );

  // --- Abort streaming ---
  const handleAbort = useCallback(() => {
    if (abortRef?.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    onAbortTyping?.();
  }, [abortRef, onAbortTyping]);

  // --- Quick output-mode buttons ---
  const canQuickSend =
    !waitingSession && !!input.trim() && !!roleId && !!projectId;

  const kindToSlash = (k: RenderKind) =>
    k === "plain"
      ? "/plain "
      : k === "markdown"
      ? "/markdown "
      : k === "code"
      ? "/code "
      : k === "poem_plain"
      ? "/poem "
      : "/poem_code ";

  /**
   * We both pass overrides (future-friendly) AND prepend the slash prefix
   * so existing ChatPage.parseRenderOverride(...) will pick it up today.
   */
  const sendWithKind = (
    kind: RenderKind,
    language?: string | null,
    filename?: string | null
  ) => {
    if (!canQuickSend) return;
    const value = input.trim();
    const prefixed = `${kindToSlash(kind)}${value}`;
    // overrides are ignored by current ChatPage (safe), but kept for later
    handleSend(prefixed, {
      kind,
      language: language ?? null,
      filename: filename ?? null,
    });
    setInput("");
  };

  return (
    <form onSubmit={handleSubmit} className="w-full">
      <label htmlFor="chat-input" className="mb-1 block text-xs text-gray-500">
        💬 Ask something to your selected AI
      </label>

      <div
        {...getRootProps()}
        ref={containerRef}
        className={`relative flex gap-2 items-end border border-gray-300 rounded-lg px-3 py-2 shadow-sm bg-white focus-within:ring-2 focus-within:ring-blue-500 ${
          waitingSession ? "opacity-50 pointer-events-none" : ""
        }`}
      >
        <textarea
          id="chat-input"
          ref={textareaRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDownLocal}
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
          disabled={waitingSession}
        >
          <Paperclip size={18} />
        </button>

        {/* Actions */}
        <div className="flex flex-col gap-2 ml-2">
          {/* Quick output-mode row */}
          <div className="flex flex-wrap gap-1 justify-end">
            <button
              type="button"
              title="Send as Plain"
              aria-label="Send as Plain"
              disabled={!canQuickSend}
              onClick={() => sendWithKind("plain")}
              className={`px-2 py-1 rounded text-xs border ${
                canQuickSend
                  ? "hover:bg-gray-100"
                  : "opacity-50 cursor-not-allowed"
              }`}
            >
              Plain
            </button>
            <button
              type="button"
              title="Send as Markdown"
              aria-label="Send as Markdown"
              disabled={!canQuickSend}
              onClick={() => sendWithKind("markdown")}
              className={`px-2 py-1 rounded text-xs border ${
                canQuickSend
                  ? "hover:bg-gray-100"
                  : "opacity-50 cursor-not-allowed"
              }`}
            >
              MD
            </button>
            <button
              type="button"
              title="Send as Code Block"
              aria-label="Send as Code Block"
              disabled={!canQuickSend}
              onClick={() => sendWithKind("code")}
              className={`px-2 py-1 rounded text-xs border font-mono ${
                canQuickSend
                  ? "hover:bg-gray-100"
                  : "opacity-50 cursor-not-allowed"
              }`}
            >
              Code
            </button>
            <button
              type="button"
              title="Send as Poem (plain)"
              aria-label="Send as Poem (plain)"
              disabled={!canQuickSend}
              onClick={() => sendWithKind("poem_plain")}
              className={`px-2 py-1 rounded text-xs border ${
                canQuickSend
                  ? "hover:bg-gray-100"
                  : "opacity-50 cursor-not-allowed"
              }`}
            >
              Poem·plain
            </button>
            <button
              type="button"
              title="Send as Poem (code-styled block)"
              aria-label="Send as Poem (code-styled block)"
              disabled={!canQuickSend}
              onClick={() => sendWithKind("poem_code")}
              className={`px-2 py-1 rounded text-xs border font-mono ${
                canQuickSend
                  ? "hover:bg-gray-100"
                  : "opacity-50 cursor-not-allowed"
              }`}
            >
              Poem⌁code
            </button>
          </div>

          <button
            type="submit"
            disabled={waitingSession || !input.trim()}
            className={`px-4 py-2 rounded-lg text-sm transition ${
              !waitingSession && input.trim()
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
