import React from "react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { vscDarkPlus } from "react-syntax-highlighter/dist/esm/styles/prism";
import { Copy, Download, FileText } from "lucide-react";
import type { GeneratedFile } from "../../types/projects";
import { downloadFile } from "../../services/fileApi";

interface FileViewerProps {
  file: GeneratedFile | null;
}

export default function FileViewer({ file }: FileViewerProps) {
  if (!file) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-center text-gray-400">
          <FileText size={64} className="mx-auto mb-4 opacity-50" />
          <p>Select a file to view its contents</p>
        </div>
      </div>
    );
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(file.content);
      // TODO: Add toast notification
      console.log("✅ Copied to clipboard");
    } catch (error) {
      console.error("Failed to copy:", error);
    }
  };

  const handleDownload = () => {
    const fileName = file.file_path.split("/").pop() || "file.txt";
    downloadFile(fileName, file.content);
  };

  const getLanguage = (lang: string): string => {
    const languageMap: Record<string, string> = {
      typescript: "typescript",
      javascript: "javascript",
      python: "python",
      jsx: "jsx",
      tsx: "tsx",
      json: "json",
      html: "html",
      css: "css",
      markdown: "markdown",
      yaml: "yaml",
      sql: "sql",
      bash: "bash",
      shell: "bash",
    };
    return languageMap[lang.toLowerCase()] || "text";
  };

  const formatSize = (bytes: number): string => {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <div className="flex flex-col h-full">
      {/* File Header */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-700 bg-gray-800">
        <div className="flex items-center gap-3">
          <FileText size={18} className="text-gray-400" />
          <div>
            <p className="text-white font-medium">{file.file_path}</p>
            <p className="text-xs text-gray-400">
              {file.language} • {formatSize(file.size)}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleCopy}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:text-white hover:bg-gray-700 rounded transition-colors"
          >
            <Copy size={16} />
            Copy
          </button>
          <button
            onClick={handleDownload}
            className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-300 hover:text-white hover:bg-gray-700 rounded transition-colors"
          >
            <Download size={16} />
            Download
          </button>
        </div>
      </div>

      {/* File Content */}
      <div className="flex-1 overflow-auto bg-gray-900">
        <SyntaxHighlighter
          language={getLanguage(file.language)}
          style={vscDarkPlus}
          showLineNumbers
          customStyle={{
            margin: 0,
            padding: "1.5rem",
            background: "transparent",
            fontSize: "14px",
          }}
          lineNumberStyle={{
            minWidth: "3em",
            paddingRight: "1em",
            color: "#6b7280",
            userSelect: "none",
          }}
        >
          {file.content}
        </SyntaxHighlighter>
      </div>
    </div>
  );
}
