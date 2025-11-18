// File: src/components/Chat/SummaryBubble.tsx
import React from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useChatStore } from "../../store/chatStore";

type Props = {
  text: string;
  /** Keep summary hidden (skeleton only) while the model is still typing */
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

  const showText = !(deferWhileTyping && isTyping);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduce ? 0 : 0.25 }}
      role="note"
      aria-live="polite"
      className={`bg-purple-50 border-l-4 border-purple-500 px-4 py-3 rounded shadow-sm ${className}`}
    >
      {showText ? (
        <motion.p
          key="summary-text"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: reduce ? 0 : 0.25 }}
          className="italic font-serif text-purple-900 text-[15px] leading-relaxed whitespace-pre-line"
        >
          {text}
        </motion.p>
      ) : (
        // Skeleton while assistant is streaming
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
