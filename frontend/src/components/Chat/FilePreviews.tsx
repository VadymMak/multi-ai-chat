// src/components/Chat/FilePreviews.tsx
import React from "react";
import { X, FileText, Image, FileCode, File } from "lucide-react";

interface FilePreviewsProps {
  files: File[];
  onRemove: (index: number) => void;
}

const getFileIcon = (file: File) => {
  const type = file.type.toLowerCase();
  if (type.includes("image")) return <Image size={16} />;
  if (type.includes("pdf"))
    return <FileText size={16} className="text-red-500" />;
  if (type.includes("text") || file.name.endsWith(".md"))
    return <FileCode size={16} />;
  return <File size={16} />;
};

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / (1024 * 1024)).toFixed(1) + " MB";
};

const FilePreviews: React.FC<FilePreviewsProps> = ({ files, onRemove }) => {
  if (files.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-2 p-2 border-t border-border">
      {files.map((file, index) => (
        <div
          key={index}
          className="flex items-center gap-2 px-3 py-1.5 bg-surface border border-border rounded-sm text-sm group hover:border-primary transition-colors"
        >
          {getFileIcon(file)}
          <span className="max-w-[200px] truncate text-text-primary">
            {file.name}
          </span>
          <span className="text-text-secondary text-xs">
            {formatFileSize(file.size)}
          </span>
          <button
            type="button"
            onClick={() => onRemove(index)}
            className="ml-1 text-text-secondary hover:text-error transition-colors"
            aria-label={`Remove ${file.name}`}
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
};

export default FilePreviews;
