// File: src/components/Chat/SummaryBubble.tsx
import React, { useState, useEffect } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Copy, Check, Download, CheckCircle, Loader2 } from "lucide-react";
import { useChatStore } from "../../store/chatStore";
import {
  useProjectStore,
  selectGenerationStatus,
} from "../../store/projectStore";
import { toast } from "../../store/toastStore";
import MarkdownMessage from "../Shared/MarkdownMessage";

type Props = {
  text: string;
  deferWhileTyping?: boolean;
  className?: string;
};

// ✅ Detect Project Builder structure markers
function isProjectBuilderOutput(text: string): boolean {
  const markers = [
    "===PROJECT_STRUCTURE_START===",
    "===FINAL_STRUCTURE_START===",
  ];
  return markers.some((marker) => text.includes(marker));
}

// ✅ Extract structure block text
function extractStructureBlock(text: string): string {
  // Try FINAL first
  const finalMatch = text.match(
    /===FINAL_STRUCTURE_START===([\s\S]*?)===FINAL_STRUCTURE_END===/
  );
  if (finalMatch) return finalMatch[0];

  // Then PROJECT
  const projectMatch = text.match(
    /===PROJECT_STRUCTURE_START===([\s\S]*?)===PROJECT_STRUCTURE_END===/
  );
  if (projectMatch) return projectMatch[0];

  return "";
}

// ✅ Extract review/suggestions text (outside of structure blocks)
function extractReviewText(text: string): string {
  let result = text;

  // Remove FINAL_STRUCTURE block
  result = result.replace(
    /===FINAL_STRUCTURE_START===[\s\S]*?===FINAL_STRUCTURE_END===/g,
    ""
  );

  // Remove PROJECT_STRUCTURE block
  result = result.replace(
    /===PROJECT_STRUCTURE_START===[\s\S]*?===PROJECT_STRUCTURE_END===/g,
    ""
  );

  // Clean up extra whitespace
  result = result.replace(/\n{3,}/g, "\n\n").trim();

  return result;
}

// ✅ Count files in structure
function countFilesInStructure(text: string): number {
  const filePattern = /^\d+\.\s+`[^`]+`/gm;
  const matches = text.match(filePattern);
  return matches?.length || 0;
}

const SummaryBubble: React.FC<Props> = ({
  text,
  deferWhileTyping = true,
  className = "",
}) => {
  const isTyping = useChatStore((s) => s.isTyping);
  const reduce = useReducedMotion();
  const [copied, setCopied] = useState(false);

  // ✅ Get generation status from store
  const generationStatus = useProjectStore(selectGenerationStatus);
  const projectId = useProjectStore((s) => s.projectId);
  const fetchGenerationStatus = useProjectStore((s) => s.fetchGenerationStatus);

  const showText = !(deferWhileTyping && isTyping);
  const isProjectBuilder = isProjectBuilderOutput(text);
  const reviewText = isProjectBuilder ? extractReviewText(text) : "";
  const structureBlock = isProjectBuilder ? extractStructureBlock(text) : "";
  const fileCount = isProjectBuilder ? countFilesInStructure(text) : 0;

  // ✅ Trigger generation status fetch when Project Builder output detected
  useEffect(() => {
    if (isProjectBuilder && projectId) {
      // Small delay to let backend start generation
      const timer = setTimeout(() => {
        fetchGenerationStatus(projectId);
      }, 1000);
      return () => clearTimeout(timer);
    }
  }, [isProjectBuilder, projectId, fetchGenerationStatus]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      toast.success("Copied to clipboard!");
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
      toast.error("Failed to copy");
    }
  };

  const handleDownload = () => {
    const filename = isProjectBuilder ? "project-structure.txt" : "summary.txt";
    const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${filename}`);
  };

  // ✅ Render generation status indicator
  const renderGenerationStatus = () => {
    if (!generationStatus) return null;

    const { status, files_generated, total_files, progress_percent } =
      generationStatus;

    if (status === "generating") {
      return (
        <div className="flex items-center gap-3 px-4 py-3 bg-blue-500/10 border border-blue-500/30 rounded-lg">
          <Loader2 size={18} className="animate-spin text-blue-400" />
          <div className="flex-1">
            <div className="text-sm text-blue-300 font-medium">
              Generating files... {files_generated}/{total_files}
            </div>
            <div className="mt-1.5 h-1.5 bg-blue-900/50 rounded-full overflow-hidden">
              <div
                className="h-full bg-gradient-to-r from-blue-500 to-cyan-400 transition-all duration-300"
                style={{ width: `${progress_percent}%` }}
              />
            </div>
          </div>
          <span className="text-xs text-blue-400">{progress_percent}%</span>
        </div>
      );
    }

    if (status === "completed" && files_generated > 0) {
      return (
        <div className="flex items-center gap-2 px-4 py-2 bg-green-500/10 border border-green-500/30 rounded-lg">
          <CheckCircle size={16} className="text-green-400" />
          <span className="text-sm text-green-300">
            ✅ {files_generated} files generated! Click "View Files" in sidebar.
          </span>
        </div>
      );
    }

    return null;
  };

  // ✅ For Project Builder - show structure + review + generation status
  if (isProjectBuilder) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: reduce ? 0 : 0.25 }}
        role="note"
        aria-live="polite"
        className={`space-y-4 ${className}`}
      >
        {/* Review/Suggestions text (if any) - BEFORE structure */}
        {reviewText && (
          <div className="group relative bg-panel border-l-4 border-blue-500 px-4 py-3 rounded shadow-sm">
            <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10">
              <button
                onClick={handleCopy}
                className="p-1.5 rounded-lg hover:bg-surface transition-all text-text-secondary hover:text-text-primary"
                title="Copy all"
              >
                {copied ? (
                  <Check size={14} className="text-green-500" />
                ) : (
                  <Copy size={14} />
                )}
              </button>
              <button
                onClick={handleDownload}
                className="p-1.5 rounded-lg hover:bg-surface transition-all text-text-secondary hover:text-text-primary"
                title="Download all"
              >
                <Download size={14} />
              </button>
            </div>

            <div
              className="font-mono text-xs text-text-primary leading-relaxed"
              style={{
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
              }}
            >
              {reviewText}
            </div>
          </div>
        )}

        {/* ✅ Generation status indicator */}
        {renderGenerationStatus()}

        {/* Raw structure block - full width */}
        {structureBlock && (
          <div className="group relative bg-[#1e1e2e] rounded-lg p-4 shadow-sm max-w-4xl">
            <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity z-10">
              <span className="text-xs text-gray-500 mr-2">
                {fileCount} files
              </span>
              <button
                onClick={async () => {
                  await navigator.clipboard.writeText(structureBlock);
                  toast.success("Structure copied!");
                }}
                className="p-1.5 rounded-lg hover:bg-white/10 transition-all text-gray-400 hover:text-white"
                title="Copy structure"
              >
                <Copy size={14} />
              </button>
            </div>
            <pre
              className="font-mono text-xs text-[#cdd6f4] leading-relaxed overflow-x-auto"
              style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}
            >
              {structureBlock}
            </pre>
          </div>
        )}

        {/* ✅ REMOVED: ProjectStructureView component */}
        {/* Files now generate automatically - check sidebar for progress */}
      </motion.div>
    );
  }

  // ✅ Normal Summary (non-Project Builder)
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduce ? 0 : 0.25 }}
      role="note"
      aria-live="polite"
      className={`group relative bg-purple-50 border-l-4 border-purple-500 px-4 py-3 rounded shadow-sm ${className}`}
    >
      {/* Copy & Download Buttons */}
      <div className="absolute top-2 right-2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        <button
          onClick={handleCopy}
          className="p-1.5 rounded-lg hover:bg-purple-100 transition-all text-purple-600 hover:text-purple-800"
          title="Copy to clipboard"
        >
          {copied ? (
            <Check size={16} className="text-success" />
          ) : (
            <Copy size={16} />
          )}
        </button>
        <button
          onClick={handleDownload}
          className="p-1.5 rounded-lg hover:bg-purple-100 transition-all text-purple-600 hover:text-purple-800"
          title="Download"
        >
          <Download size={16} />
        </button>
      </div>

      {showText ? (
        <motion.div
          key="summary-text"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduce ? 0 : 0.25 }}
          className="italic font-serif text-purple-900 text-[15px] leading-relaxed"
        >
          <MarkdownMessage text={text} isUser={false} kind="markdown" />
        </motion.div>
      ) : (
        <div className="animate-pulse space-y-2">
          <div className="h-3 w-11/12 rounded bg-purple-200/60" />
          <div className="h-3 w-10/12 rounded bg-purple-200/50" />
          <div className="h-3 w-9/12 rounded bg-purple-200/40" />
        </div>
      )}
    </motion.div>
  );
};

export default SummaryBubble;
