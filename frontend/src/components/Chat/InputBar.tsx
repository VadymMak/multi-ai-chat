import React, { useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Paperclip } from "lucide-react";

interface InputBarProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: (text?: string) => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAbortTyping?: () => void;
  onFileDrop: (file: File) => Promise<string | null>;
  abortRef?: React.RefObject<AbortController | null>;
}

const InputBar: React.FC<InputBarProps> = ({
  input,
  setInput,
  handleSend,
  handleKeyDown,
  onAbortTyping,
  onFileDrop,
  abortRef,
}) => {
  const onDrop = useCallback(
    async (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0) {
        const summary = await onFileDrop(acceptedFiles[0]);
        if (summary) {
          setInput("");
          handleSend(summary);
        }
      }
    },
    [onFileDrop, handleSend, setInput]
  );

  const { getRootProps, getInputProps, open } = useDropzone({
    onDrop,
    noClick: true,
    multiple: false,
    accept: {
      "application/pdf": [".pdf"],
      "text/plain": [".txt"],
      "application/json": [".json"],
      "text/csv": [".csv"],
    },
  });

  const handleSubmit = useCallback(
    (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      if (input.trim()) {
        handleSend(input);
        setInput("");
      }
    },
    [handleSend, input, setInput]
  );

  return (
    <footer className="p-4 sm:pb-6 md:pb-8 border-t bg-white">
      <div className="max-w-4xl mx-auto w-full px-4">
        <form onSubmit={handleSubmit} className="flex flex-col gap-2">
          <label htmlFor="chat-input" className="text-sm text-gray-600">
            💬 Ask something to your selected AI
          </label>

          <div
            {...getRootProps()}
            className="relative flex gap-2 items-end border border-gray-300 rounded-lg px-3 py-2 shadow-sm bg-white focus-within:ring-2 focus-within:ring-blue-500"
          >
            <textarea
              id="chat-input"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask something... or drop a file here"
              rows={3}
              className="flex-1 resize-none outline-none text-sm max-h-40 overflow-y-auto placeholder:text-gray-400 leading-snug"
            />
            <input {...getInputProps()} />

            <button
              type="button"
              onClick={open}
              className="text-gray-500 hover:text-blue-600 p-1"
              title="Upload file"
            >
              <Paperclip size={18} />
            </button>

            <div className="flex flex-col gap-2 ml-2">
              <button
                type="submit"
                className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition text-sm"
              >
                Send
              </button>

              {onAbortTyping && (
                <button
                  type="button"
                  onClick={onAbortTyping}
                  className="px-4 py-2 bg-gray-200 text-red-600 hover:text-red-800 rounded-lg text-sm"
                >
                  Abort
                </button>
              )}
            </div>
          </div>
        </form>
      </div>
    </footer>
  );
};

export default InputBar;
