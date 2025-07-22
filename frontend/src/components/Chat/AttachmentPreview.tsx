import React from "react";
import type { Attachment } from "../../types/chat";
import { Download, File, Image, FileText } from "lucide-react";

interface AttachmentPreviewProps {
  attachment: Attachment;
  onDownload?: () => void;
}

export const AttachmentPreview: React.FC<AttachmentPreviewProps> = ({
  attachment,
  onDownload,
}) => {
  const getIcon = () => {
    const fileType = (attachment as any).file_type || "document";
    switch (fileType) {
      case "image":
        return <Image className="w-5 h-5" />;
      case "data":
        return <FileText className="w-5 h-5" />;
      default:
        return <File className="w-5 h-5" />;
    }
  };

  const formatSize = (bytes?: number) => {
    if (!bytes) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const filename = (attachment as any).original_filename || attachment.name;
  const downloadUrl = attachment.url;

  return (
    <div className="flex items-center gap-3 p-3 bg-zinc-800 rounded-lg border border-zinc-700 hover:border-zinc-600 transition-colors">
      {/* Icon */}
      <div className="flex-shrink-0 text-zinc-400">{getIcon()}</div>

      {/* File info */}
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium text-zinc-200 truncate">
          {filename}
        </div>
        {attachment.size && (
          <div className="text-xs text-zinc-500">
            {formatSize(attachment.size)}
          </div>
        )}
      </div>

      {/* Download button */}
      <a
        href={downloadUrl}
        download={filename}
        onClick={onDownload}
        className="flex-shrink-0 p-2 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-700 rounded transition-colors"
        title="Download"
      >
        <Download className="w-4 h-4" />
      </a>
    </div>
  );
};
