// src/components/Chat/InputBar.tsx
import React from "react";
import { useDropzone } from "react-dropzone";
import { Paperclip } from "lucide-react"; // or use from react-icons

interface InputBarProps {
  input: string;
  setInput: (val: string) => void;
  handleSend: () => void;
  handleKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onAbortTyping: () => void;
  onFileDrop: (file: File) => void;
}

const InputBar: React.FC<InputBarProps> = ({
  input,
  setInput,
  handleSend,
  handleKeyDown,
  onAbortTyping,
  onFileDrop,
}) => {
  const { getRootProps, getInputProps, open } = useDropzone({
    onDrop: (acceptedFiles) => {
      if (acceptedFiles.length > 0) {
        onFileDrop(acceptedFiles[0]);
      }
    },
    noClick: true,
    multiple: false,
    accept: {
      "text/plain": [".txt"],
      "application/pdf": [".pdf"],
      "text/csv": [".csv"],
      "application/json": [".json"],
    },
  });

  return (
    <footer className="p-4 pb-24 sm:pb-20 md:pb-16 border-t bg-white">
      <div className="max-w-4xl mx-auto w-full px-4">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="flex flex-col gap-2"
        >
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
              className="flex-1 resize-none outline-none text-sm max-h-32 overflow-y-auto placeholder:text-gray-400"
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
              <button
                type="button"
                onClick={onAbortTyping}
                className="px-4 py-2 bg-gray-200 text-red-600 hover:text-red-800 rounded-lg text-sm"
              >
                Abort
              </button>
            </div>
          </div>
        </form>
      </div>
    </footer>
  );
};

export default InputBar;
