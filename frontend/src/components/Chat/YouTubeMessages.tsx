import React from "react";
import type { ChatMessage } from "../../types/chat";
import { convertMarkdownLinkToHTML } from "../../utils/markdown";

interface YouTubeMessagesProps {
  message: ChatMessage;
}

const YouTubeMessages: React.FC<YouTubeMessagesProps> = ({ message }) => {
  const lines = message.text.split("\n").filter((line) => line.trim());

  console.log("[YouTubeMessages] Full message object:", message);
  console.log("[YouTubeMessages] Parsed lines:", lines);

  return (
    <div
      className="bg-red-50 border-l-4 border-red-400 px-4 py-3 rounded shadow-sm"
      key={message.id}
    >
      <p className="text-red-800 font-medium mb-2">🎬 YouTube Results</p>
      <ul className="space-y-2 text-sm text-red-900">
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

export default YouTubeMessages;
