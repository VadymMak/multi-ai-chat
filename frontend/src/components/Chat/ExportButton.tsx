/**
 * Export Conversation Button
 * Экспорт текущей беседы в разных форматах
 */
import React, { useState } from "react";
import { Download, FileText, Code, FileJson } from "lucide-react";
import { useChatStore } from "../../store/chatStore";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import { toast } from "../../store/toastStore";

type ExportFormat = "markdown" | "txt" | "json";

export default function ExportButton() {
  const [isOpen, setIsOpen] = useState(false);

  const messages = useChatStore((s) => s.messages);
  const chatSessionId = useChatStore((s) => s.chatSessionId);
  const role = useMemoryStore((s) => s.role);
  const projectId = useProjectStore((s) => s.projectId);

  /**
   * Фильтрация сообщений текущей сессии
   */
  const getCurrentMessages = () => {
    return messages.filter(
      (msg) =>
        String(msg.project_id) === String(projectId) &&
        String(msg.role_id) === String(role?.id) &&
        String(msg.chat_session_id) === String(chatSessionId)
    );
  };

  /**
   * Форматирование в Markdown
   */
  const exportToMarkdown = () => {
    const currentMessages = getCurrentMessages();

    if (currentMessages.length === 0) {
      toast.error("No messages to export");
      return;
    }

    let markdown = `# Chat Conversation\n\n`;
    markdown += `**Role:** ${role?.name || "Unknown"}\n`;
    markdown += `**Date:** ${new Date().toLocaleDateString()}\n`;
    markdown += `**Messages:** ${currentMessages.length}\n\n`;
    markdown += `---\n\n`;

    currentMessages.forEach((msg) => {
      const sender = msg.sender === "user" ? "👤 You" : `🤖 ${msg.sender}`;
      const timestamp = msg.timestamp
        ? new Date(msg.timestamp).toLocaleString()
        : "";

      markdown += `## ${sender}\n`;
      if (timestamp) markdown += `*${timestamp}*\n\n`;
      markdown += `${msg.text}\n\n`;
      markdown += `---\n\n`;
    });

    downloadFile(markdown, "conversation.md", "text/markdown");
    toast.success("Exported to Markdown!");
  };

  /**
   * Форматирование в Plain Text
   */
  const exportToText = () => {
    const currentMessages = getCurrentMessages();

    if (currentMessages.length === 0) {
      toast.error("No messages to export");
      return;
    }

    let text = `Chat Conversation\n`;
    text += `================\n\n`;
    text += `Role: ${role?.name || "Unknown"}\n`;
    text += `Date: ${new Date().toLocaleDateString()}\n`;
    text += `Messages: ${currentMessages.length}\n\n`;
    text += `================\n\n`;

    currentMessages.forEach((msg, idx) => {
      const sender = msg.sender === "user" ? "You" : msg.sender.toUpperCase();
      const timestamp = msg.timestamp
        ? new Date(msg.timestamp).toLocaleString()
        : "";

      text += `[${idx + 1}] ${sender}`;
      if (timestamp) text += ` - ${timestamp}`;
      text += `\n${msg.text}\n\n`;
      text += `---\n\n`;
    });

    downloadFile(text, "conversation.txt", "text/plain");
    toast.success("Exported to Text!");
  };

  /**
   * Форматирование в JSON
   */
  const exportToJSON = () => {
    const currentMessages = getCurrentMessages();

    if (currentMessages.length === 0) {
      toast.error("No messages to export");
      return;
    }

    const exportData = {
      metadata: {
        role: role?.name || "Unknown",
        roleId: role?.id,
        projectId: projectId,
        sessionId: chatSessionId,
        exportDate: new Date().toISOString(),
        messageCount: currentMessages.length,
      },
      messages: currentMessages.map((msg) => ({
        id: msg.id,
        sender: msg.sender,
        text: msg.text,
        timestamp: msg.timestamp,
        isSummary: msg.isSummary || false,
        render: msg.render || null,
      })),
    };

    const json = JSON.stringify(exportData, null, 2);
    downloadFile(json, "conversation.json", "application/json");
    toast.success("Exported to JSON!");
  };

  /**
   * Скачивание файла
   */
  const downloadFile = (
    content: string,
    filename: string,
    mimeType: string
  ) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  /**
   * Обработчик экспорта
   */
  const handleExport = (format: ExportFormat) => {
    setIsOpen(false);

    switch (format) {
      case "markdown":
        exportToMarkdown();
        break;
      case "txt":
        exportToText();
        break;
      case "json":
        exportToJSON();
        break;
    }
  };

  return (
    <div className="relative">
      {/* Export Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="p-2 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-primary"
        title="Export conversation"
      >
        <Download size={20} />
      </button>

      {/* Dropdown Menu */}
      {isOpen && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setIsOpen(false)}
          />

          {/* Menu */}
          <div className="absolute right-0 top-full mt-2 w-56 bg-panel border border-border rounded-lg shadow-lg z-50 overflow-hidden">
            <div className="px-3 py-2 border-b border-border">
              <p className="text-xs font-semibold text-text-primary">
                Export Conversation
              </p>
            </div>

            <div className="py-1">
              {/* Markdown */}
              <button
                onClick={() => handleExport("markdown")}
                className="w-full px-3 py-2 flex items-center gap-3 hover:bg-surface transition text-left"
              >
                <FileText size={16} className="text-primary" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-text-primary">
                    Markdown
                  </div>
                  <div className="text-xs text-text-secondary">.md format</div>
                </div>
              </button>

              {/* Plain Text */}
              <button
                onClick={() => handleExport("txt")}
                className="w-full px-3 py-2 flex items-center gap-3 hover:bg-surface transition text-left"
              >
                <Code size={16} className="text-success" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-text-primary">
                    Plain Text
                  </div>
                  <div className="text-xs text-text-secondary">.txt format</div>
                </div>
              </button>

              {/* JSON */}
              <button
                onClick={() => handleExport("json")}
                className="w-full px-3 py-2 flex items-center gap-3 hover:bg-surface transition text-left"
              >
                <FileJson size={16} className="text-warning" />
                <div className="flex-1">
                  <div className="text-sm font-medium text-text-primary">
                    JSON
                  </div>
                  <div className="text-xs text-text-secondary">
                    .json format
                  </div>
                </div>
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
