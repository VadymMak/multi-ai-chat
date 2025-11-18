/**
 * Message Actions Component
 * Действия для отдельного сообщения
 */
import React, { useState } from "react";
import { Copy, Edit2, RotateCw, Trash2, Check, Download } from "lucide-react";
import { toast } from "../../store/toastStore";

interface MessageActionsProps {
  messageId: string;
  content: string;
  role: "user" | "assistant";
  onEdit?: () => void;
  onRegenerate?: () => void;
  onDelete?: () => void;
  className?: string;
}

export default function MessageActions({
  messageId,
  content,
  role,
  onEdit,
  onRegenerate,
  onDelete,
  className = "",
}: MessageActionsProps) {
  const [copied, setCopied] = useState(false);

  /**
   * Копирование в буфер обмена
   */
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      toast.success("Copied to clipboard!");

      // Сброс через 2 секунды
      setTimeout(() => setCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy:", error);
      toast.error("Failed to copy");
    }
  };

  /**
   * Скачать сообщение как файл
   */
  const handleDownload = () => {
    const blob = new Blob([content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `message-${messageId.slice(0, 8)}.txt`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Message downloaded!");
  };

  return (
    <div
      className={`flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ${className}`}
    >
      {/* Copy Button */}
      <button
        onClick={handleCopy}
        className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-primary"
        title="Copy to clipboard"
      >
        {copied ? (
          <Check size={16} className="text-success" />
        ) : (
          <Copy size={16} />
        )}
      </button>

      {/* Edit Button (только для user сообщений) */}
      {role === "user" && onEdit && (
        <button
          onClick={onEdit}
          className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-primary"
          title="Edit message"
        >
          <Edit2 size={16} />
        </button>
      )}

      {/* Regenerate Button (только для assistant сообщений) */}
      {role === "assistant" && onRegenerate && (
        <button
          onClick={onRegenerate}
          className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-primary"
          title="Regenerate response"
        >
          <RotateCw size={16} />
        </button>
      )}

      {/* Download Button */}
      <button
        onClick={handleDownload}
        className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-primary"
        title="Download message"
      >
        <Download size={16} />
      </button>

      {/* Delete Button */}
      {onDelete && (
        <button
          onClick={onDelete}
          className="p-1.5 rounded-lg hover:bg-surface transition-colors text-text-secondary hover:text-error"
          title="Delete message"
        >
          <Trash2 size={16} />
        </button>
      )}
    </div>
  );
}
