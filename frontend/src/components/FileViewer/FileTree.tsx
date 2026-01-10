import React, { useState } from "react";
import {
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  FolderOpen,
} from "lucide-react";
import type { FileNode, GeneratedFile } from "../../types/projects";

interface FileTreeProps {
  nodes: FileNode[];
  selectedFile: GeneratedFile | null;
  onSelectFile: (file: GeneratedFile) => void;
}

export default function FileTree({
  nodes,
  selectedFile,
  onSelectFile,
}: FileTreeProps) {
  return (
    <div className="p-4">
      {nodes.map((node) => (
        <TreeNode
          key={node.path}
          node={node}
          selectedFile={selectedFile}
          onSelectFile={onSelectFile}
          level={0}
        />
      ))}
    </div>
  );
}

interface TreeNodeProps {
  node: FileNode;
  selectedFile: GeneratedFile | null;
  onSelectFile: (file: GeneratedFile) => void;
  level: number;
}

function TreeNode({ node, selectedFile, onSelectFile, level }: TreeNodeProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const isSelected = selectedFile?.file_path === node.file?.file_path;

  const handleClick = () => {
    if (node.type === "directory") {
      setIsExpanded(!isExpanded);
    } else if (node.file) {
      onSelectFile(node.file);
    }
  };

  return (
    <div>
      <div
        className={`flex items-center gap-2 py-1.5 px-2 rounded cursor-pointer transition-colors ${
          isSelected
            ? "bg-blue-600 text-white"
            : "text-gray-300 hover:bg-gray-700"
        }`}
        style={{ paddingLeft: `${level * 16 + 8}px` }}
        onClick={handleClick}
      >
        {node.type === "directory" ? (
          <>
            {isExpanded ? (
              <ChevronDown size={16} className="flex-shrink-0" />
            ) : (
              <ChevronRight size={16} className="flex-shrink-0" />
            )}
            {isExpanded ? (
              <FolderOpen size={16} className="flex-shrink-0 text-blue-400" />
            ) : (
              <Folder size={16} className="flex-shrink-0 text-blue-400" />
            )}
          </>
        ) : (
          <>
            <div className="w-4" /> {/* Spacer for alignment */}
            <File size={16} className="flex-shrink-0 text-gray-400" />
          </>
        )}
        <span className="text-sm truncate">{node.name}</span>
      </div>

      {node.type === "directory" && isExpanded && node.children && (
        <div>
          {node.children.map((child) => (
            <TreeNode
              key={child.path}
              node={child}
              selectedFile={selectedFile}
              onSelectFile={onSelectFile}
              level={level + 1}
            />
          ))}
        </div>
      )}
    </div>
  );
}
