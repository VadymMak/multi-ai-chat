import React from "react";
import type { ChatMessage } from "../../types/chat";
import { convertMarkdownLinkToHTML } from "../../utils/markdown";

interface Props {
  message: ChatMessage;
}

const WebSearchResults: React.FC<Props> = ({ message }) => {
  console.log("[WebSearchResults] Rendering message:", message);

  const lines = message.text.split("\n").filter((line) => line.trim());
  console.log("[WebSearchResults] Parsed lines:", lines);

  return (
    <div className="bg-blue-50 border-l-4 border-blue-500 px-4 py-3 rounded shadow-sm">
      <p className="text-blue-800 font-medium mb-2">🌐 Web Results</p>
      <ul className="space-y-2 text-sm text-blue-900">
        {lines.map((line, index) => {
          const html = convertMarkdownLinkToHTML(line);
          return (
            <li
              key={`${message.id}-line-${index}`}
              className="leading-relaxed whitespace-pre-line underline-offset-2 hover:underline"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          );
        })}
      </ul>
    </div>
  );
};

export default WebSearchResults;
