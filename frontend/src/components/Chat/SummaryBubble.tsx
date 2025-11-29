// File: src/components/Chat/SummaryBubble.tsx
import React, { useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { Copy, Check } from "lucide-react";
import { useChatStore } from "../../store/chatStore";
import { toast } from "../../store/toastStore";
import MarkdownMessage from "../Shared/MarkdownMessage";

type Props = {
  text: string;
  deferWhileTyping?: boolean;
  className?: string;
};

const SummaryBubble: React.FC<Props> = ({
  text,
  deferWhileTyping = true,
  className = "",
}) => {
  const isTyping = useChatStore((s) => s.isTyping);
  const reduce = useReducedMotion();
  const [copied, setCopied] = useState(false);

  const showText = !(deferWhileTyping && isTyping);

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

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduce ? 0 : 0.25 }}
      role="note"
      aria-live="polite"
      className={`group relative bg-purple-50 border-l-4 border-purple-500 px-4 py-3 rounded shadow-sm ${className}`}
    >
      {/* Copy Button - appears on hover */}
      <button
        onClick={handleCopy}
        className="absolute top-2 right-2 p-1.5 rounded-lg hover:bg-purple-100 transition-all text-purple-600 hover:text-purple-800 opacity-0 group-hover:opacity-100"
        title="Copy to clipboard"
        aria-label="Copy summary to clipboard"
      >
        {copied ? (
          <Check size={16} className="text-success" />
        ) : (
          <Copy size={16} />
        )}
      </button>
      {showText ? (
        <motion.div
          key="summary-text"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduce ? 0 : 0.25 }}
          className="italic font-serif text-purple-900 text-[15px] leading-relaxed"
        >
          {/* ← БЫЛО: {text} — СТАЛО: */}
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
