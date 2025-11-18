// File: src/components/Chat/TypingIndicator.tsx
import React from "react";
import { motion, useReducedMotion, type Transition } from "framer-motion";

type Props = {
  small?: boolean;
  className?: string;
  label?: string;
};

const TypingIndicator: React.FC<Props> = ({
  small = false,
  className = "",
  label = "Assistant is typing…",
}) => {
  const prefersReducedMotion = useReducedMotion();
  const dotSize = small ? "w-2 h-2" : "w-2.5 h-2.5";

  const baseTransition: Partial<Transition> = prefersReducedMotion
    ? { duration: 1.2, repeat: Infinity, ease: "linear" }
    : {
        duration: 0.6,
        repeat: Infinity,
        repeatType: "reverse",
        ease: "easeInOut",
      };

  const animate = prefersReducedMotion
    ? { opacity: [1, 0.6, 1] }
    : { y: ["0%", "-40%", "0%"] };

  return (
    <div
      role="status"
      aria-live="polite"
      aria-label={label}
      className={`absolute bottom-4 left-4 flex items-center gap-1 px-4 py-2 bg-surface/80 backdrop-blur-sm rounded-lg border border-border ${className}`}
      style={{ zIndex: 10 }}
    >
      {[0, 0.15, 0.3].map((delay, i) => (
        <motion.span
          key={i}
          className={`${dotSize} bg-gray-400 dark:bg-gray-300 rounded-full`}
          animate={animate}
          transition={{ ...baseTransition, delay }}
        />
      ))}
    </div>
  );
};

export default TypingIndicator;
