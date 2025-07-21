import React from "react";
import { motion } from "framer-motion";

const bounceTransition = {
  duration: 0.6,
  repeat: Infinity,
  repeatType: "reverse" as const,
  ease: "easeInOut" as const,
};

const TypingIndicator: React.FC = () => {
  return (
    <div className="flex items-center gap-1 px-4 py-2">
      {[0, 0.15, 0.3].map((delay, i) => (
        <motion.span
          key={i}
          className="w-2.5 h-2.5 bg-gray-400 rounded-full"
          animate={{ y: ["0%", "-40%", "0%"] }}
          transition={{ ...bounceTransition, delay }}
        />
      ))}
    </div>
  );
};

export default TypingIndicator;
