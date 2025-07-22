import React from "react";

interface SummaryBubbleProps {
  text: string;
}

const SummaryBubble: React.FC<SummaryBubbleProps> = ({ text }) => {
  return (
    <div className="bg-purple-50 border-l-4 border-purple-500 px-4 py-3 rounded shadow-sm">
      <p className="italic font-serif text-purple-900 text-[15px] leading-relaxed whitespace-pre-line">
        {text}
      </p>
    </div>
  );
};

export default SummaryBubble;
