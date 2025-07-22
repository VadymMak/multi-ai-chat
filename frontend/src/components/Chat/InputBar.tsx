// File: src/components/Chat/InputBar.tsx
import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  useMemo,
} from "react";
import { useDropzone } from "react-dropzone";
import { Paperclip } from "lucide-react";

import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { useChatStore } from "../../store/chatStore";
import FilePreviews from "./FilePreviews";
import type { RenderKind } from "../../types/chat";

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
    overrides?: InputOverrides,
    attachments?: File[]
  ) => void | Promise<void>;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAbortTyping?: () => void;
  abortRef?: React.RefObject<AbortController | null>;
}

const MAX_TEXTAREA_PX = 240;

const InputBar: React.FC<InputBarProps> = ({
  input,
  setInput,
  handleSend,
  handleKeyDown,
  onAbortTyping,
  abortRef,
}) => {
  const roleId = useMemoryStore((s) => s.role?.id ?? null);
  const projectId = useProjectStore((s) => s.projectId);
  const sessionReady = useChatStore((s) => s.sessionReady);
  const waitingSession = !sessionReady;

  // Local composer state
  const [text, setText] = useState<string>(input ?? "");
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  useEffect(() => {
    if (input !== text) setText(input ?? "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);

  const containerRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const sendingRef = useRef(false);
  const [isSending, setIsSending] = useState(false);
  const composingRef = useRef(false);

  // Auto-grow
  const autosize = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(el.scrollHeight, MAX_TEXTAREA_PX);
    el.style.height = `${next}px`;
  }, []);

  useEffect(() => {
    autosize();
  }, [autosize]);

  const currentOverrides = useMemo<InputOverrides>(
    () => ({ kind: "markdown" }),
    []
  );

  // Common send action - now includes pending files
  const sendCurrent = useCallback(async () => {
    if (sendingRef.current) return;
    if (composingRef.current) return;
    if (waitingSession) return;

    const value = text.trim();
    if (!value || !roleId || !projectId) return;

    sendingRef.current = true;
    setIsSending(true);

    // Clear text and files synchronously for instant UX
    setText("");
    setInput("");
    const filesToSend = [...pendingFiles];
    setPendingFiles([]);
    requestAnimationFrame(() => autosize());

    try {
      await handleSend(value, currentOverrides, filesToSend);
    } finally {
      sendingRef.current = false;
      setIsSending(false);
    }
  }, [
    waitingSession,
    text,
    roleId,
    projectId,
    pendingFiles,
    handleSend,
    currentOverrides,
    setInput,
    autosize,
  ]);

  // File drop - now adds to pending files instead of uploading immediately
  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (waitingSession) return;
      if (acceptedFiles.length > 0 && roleId && projectId) {
        setPendingFiles((prev) => [...prev, ...acceptedFiles]);
        requestAnimationFrame(() => autosize());
      }
    },
    [waitingSession, roleId, projectId, autosize]
  );

  const removeFile = useCallback((index: number) => {
    setPendingFiles((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const { getRootProps, getInputProps, open } = useDropzone({
    onDrop,
    noClick: true,
    multiple: true,
    accept: {
      "application/pdf": [".pdf"],
      "text/plain": [".txt", ".log", ".md"],
      "application/json": [".json"],
      "text/csv": [".csv"],
      "image/*": [".png", ".jpg", ".jpeg", ".webp"],
      "application/vnd.ms-excel": [".xls"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [
        ".xlsx",
      ],
      "application/msword": [".doc"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        [".docx"],
    },
    disabled: waitingSession || isSending,
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
        setPendingFiles((prev) => [...prev, file!]);
        requestAnimationFrame(() => autosize());
      }
    },
    [waitingSession, roleId, projectId, autosize]
  );

  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      void sendCurrent();
    },
    [sendCurrent]
  );

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

  const onCompositionStart = () => (composingRef.current = true);
  const onCompositionEnd = () => (composingRef.current = false);

  const canSend =
    !waitingSession && !isSending && !!text.trim() && !!roleId && !!projectId;

  return (
    <form onSubmit={handleSubmit} className="w-full" aria-busy={isSending}>
      <div className="flex flex-col">
        {/* File previews */}
        {pendingFiles.length > 0 && (
          <FilePreviews files={pendingFiles} onRemove={removeFile} />
        )}

        {/* Main input area */}
        <div
          {...getRootProps()}
          ref={containerRef}
          className={`relative flex gap-2 items-end border border-border rounded px-3 py-2 bg-panel focus-within:border-primary ${
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
              pendingFiles.length > 0
                ? "Type a message about the files..."
                : "Type a message..."
            }
            rows={2}
            disabled={waitingSession}
            data-gramm="false"
            aria-disabled={waitingSession}
            style={{
              minHeight: "60px",
              maxHeight: "60px",
              height: "60px",
            }}
            className="flex-1 resize-none outline-none text-sm overflow-y-auto placeholder:text-text-secondary leading-snug disabled:opacity-50 bg-transparent text-text-primary"
          />

          {/* Hidden input for dropzone */}
          <input {...getInputProps()} />

          {/* Actions - right aligned */}
          <div className="flex items-center gap-2 ml-auto">
            {/* Attach button */}
            <button
              type="button"
              onClick={open}
              className={`text-text-secondary hover:text-primary p-1 ${
                pendingFiles.length > 0 ? "text-primary" : ""
              }`}
              title="Upload file"
              aria-label="Upload file"
              disabled={waitingSession || isSending}
              aria-disabled={waitingSession || isSending}
            >
              <Paperclip size={18} />
              {pendingFiles.length > 0 && (
                <span className="absolute -top-1 -right-1 bg-primary text-white text-xs rounded-full w-4 h-4 flex items-center justify-center">
                  {pendingFiles.length}
                </span>
              )}
            </button>

            {/* Send button */}
            <button
              type="submit"
              disabled={!canSend}
              aria-disabled={!canSend}
              className={`px-4 py-2 rounded-sm text-sm transition font-semibold ${
                canSend
                  ? "bg-primary text-text-primary hover:opacity-90"
                  : "bg-surface text-text-secondary cursor-not-allowed border border-border"
              }`}
              aria-label="Send message"
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </form>
  );
};

export default InputBar;
