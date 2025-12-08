import React, { useState, useEffect } from "react";
import { X, Download, Loader2 } from "lucide-react";
import { useProjectStore } from "../../store/projectStore";
import FileTree from "./FileTree";
import FileViewer from "./FileViewer";
import type { FileNode, GeneratedFile } from "../../types/projects";
import { downloadFile } from "../../services/fileApi";
import JSZip from "jszip";

interface FilesModalProps {
  isOpen: boolean;
  onClose: () => void;
  projectId: number;
  projectName: string;
}

export default function FilesModal({
  isOpen,
  onClose,
  projectId,
  projectName,
}: FilesModalProps) {
  const {
    generatedFiles,
    filesLoading,
    filesError,
    fetchGeneratedFiles,
    clearGeneratedFiles,
  } = useProjectStore();
  const [selectedFile, setSelectedFile] = useState<GeneratedFile | null>(null);
  const [fileTree, setFileTree] = useState<FileNode[]>([]);

  // Fetch files when modal opens
  useEffect(() => {
    if (isOpen && projectId) {
      fetchGeneratedFiles(projectId);
    }
    return () => {
      if (!isOpen) {
        clearGeneratedFiles();
        setSelectedFile(null);
      }
    };
  }, [isOpen, projectId]);

  // Build file tree from flat file list
  useEffect(() => {
    if (generatedFiles.length > 0) {
      const tree = buildFileTree(generatedFiles);
      setFileTree(tree);

      // Auto-select first file
      if (!selectedFile && generatedFiles.length > 0) {
        setSelectedFile(generatedFiles[0]);
      }
    }
  }, [generatedFiles]);

  const buildFileTree = (files: GeneratedFile[]): FileNode[] => {
    // Use an internal type for building the tree
    interface TempNode {
      name: string;
      path: string;
      type: "file" | "directory";
      children?: Record<string, TempNode>;
      file?: GeneratedFile;
    }

    const root: Record<string, TempNode> = {};

    files.forEach((file) => {
      const parts = file.file_path.split("/");
      let current = root;

      parts.forEach((part, index) => {
        const isFile = index === parts.length - 1;
        const path = parts.slice(0, index + 1).join("/");

        if (!current[part]) {
          current[part] = {
            name: part,
            path: path,
            type: isFile ? "file" : "directory",
            children: isFile ? undefined : {},
            file: isFile ? file : undefined,
          };
        }

        if (!isFile && current[part].children) {
          current = current[part].children;
        }
      });
    });

    // Convert temp structure to final FileNode structure
    const convertToArray = (obj: Record<string, TempNode>): FileNode[] => {
      return Object.values(obj)
        .map(
          (node): FileNode => ({
            name: node.name,
            path: node.path,
            type: node.type,
            children: node.children ? convertToArray(node.children) : undefined,
            file: node.file,
          })
        )
        .sort((a, b) => {
          if (a.type !== b.type) return a.type === "directory" ? -1 : 1;
          return a.name.localeCompare(b.name);
        });
    };

    return convertToArray(root);
  };

  const handleDownloadAll = async () => {
    if (generatedFiles.length === 0) return;

    const zip = new JSZip();

    // Add each file to ZIP with correct folder structure
    generatedFiles.forEach((file) => {
      zip.file(file.file_path, file.content || "");
    });

    // Generate ZIP and download
    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${projectName}.zip`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-50"
      onClick={onClose}
    >
      <div
        className="bg-gray-900 rounded-lg shadow-xl w-[90vw] h-[90vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-700">
          <h2 className="text-xl font-semibold text-white">
            Generated Files - {projectName}
          </h2>
          <div className="flex items-center gap-3">
            {generatedFiles.length > 0 && (
              <button
                onClick={handleDownloadAll}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
              >
                <Download size={18} />
                Download All
              </button>
            )}
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white transition-colors"
            >
              <X size={24} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 flex overflow-hidden">
          {filesLoading ? (
            <div className="flex-1 flex items-center justify-center">
              <Loader2 className="animate-spin text-blue-500" size={48} />
            </div>
          ) : filesError ? (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <p className="text-red-400 text-lg mb-2">Error loading files</p>
                <p className="text-gray-400">{filesError}</p>
              </div>
            </div>
          ) : generatedFiles.length === 0 ? (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-gray-400 text-lg">No files generated yet</p>
            </div>
          ) : (
            <>
              {/* Left: File Tree */}
              <div className="w-80 border-r border-gray-700 overflow-y-auto bg-gray-800">
                <FileTree
                  nodes={fileTree}
                  selectedFile={selectedFile}
                  onSelectFile={setSelectedFile}
                />
              </div>

              {/* Right: File Viewer */}
              <div className="flex-1 overflow-hidden">
                <FileViewer file={selectedFile} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
