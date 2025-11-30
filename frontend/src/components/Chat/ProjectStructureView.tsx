// File: frontend/src/components/Chat/ProjectStructureView.tsx
import React, { useState, useMemo } from "react";
import {
  ChevronDown,
  ChevronRight,
  FileCode,
  Play,
  Check,
  AlertCircle,
  Loader2,
  Download,
  Terminal,
  X,
  Copy,
  Eye,
  Hammer,
} from "lucide-react";
import {
  parseProjectStructure,
  ParsedFile,
  ParsedProjectStructure,
} from "../../utils/projectStructureParser";
import { toast } from "../../store/toastStore";

interface Props {
  text: string;
  onGenerateFile: (
    file: ParsedFile,
    structure: ParsedProjectStructure
  ) => Promise<string>;
}

const ProjectStructureView: React.FC<Props> = ({ text, onGenerateFile }) => {
  const [files, setFiles] = useState<ParsedFile[]>([]);
  const [expandedSections, setExpandedSections] = useState<Set<string>>(
    new Set(["files"])
  );
  const [generatingFile, setGeneratingFile] = useState<number | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [viewingFile, setViewingFile] = useState<ParsedFile | null>(null);

  const structure = useMemo(() => parseProjectStructure(text), [text]);

  React.useEffect(() => {
    if (structure && !initialized) {
      setFiles(structure.files);
      setInitialized(true);
    }
  }, [structure, initialized]);

  if (!structure || structure.files.length === 0) {
    return null;
  }

  const toggleSection = (section: string) => {
    setExpandedSections((prev) => {
      const next = new Set(prev);
      if (next.has(section)) {
        next.delete(section);
      } else {
        next.add(section);
      }
      return next;
    });
  };

  const handleGenerateFile = async (file: ParsedFile, e: React.MouseEvent) => {
    e.stopPropagation();
    if (generatingFile !== null) return;

    setGeneratingFile(file.number);
    setFiles((prev) =>
      prev.map((f) =>
        f.number === file.number ? { ...f, status: "generating" } : f
      )
    );

    try {
      const code = await onGenerateFile(file, structure);
      setFiles((prev) =>
        prev.map((f) =>
          f.number === file.number ? { ...f, status: "done", code } : f
        )
      );
      toast.success(`Generated ${file.path}`);
    } catch (error) {
      console.error("Failed to generate file:", error);
      setFiles((prev) =>
        prev.map((f) =>
          f.number === file.number ? { ...f, status: "error" } : f
        )
      );
      toast.error(`Failed to generate ${file.path}`);
    } finally {
      setGeneratingFile(null);
    }
  };

  const handleFileClick = (file: ParsedFile) => {
    if (file.status === "done" && file.code) {
      setViewingFile(file);
    }
  };

  const handleCopyCode = async () => {
    if (viewingFile?.code) {
      await navigator.clipboard.writeText(viewingFile.code);
      toast.success("Code copied!");
    }
  };

  const handleDownloadFile = (file: ParsedFile) => {
    if (!file.code) return;

    const blob = new Blob([file.code], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    const filename = file.path.split("/").pop() || file.path;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast.success(`Downloaded ${filename}`);
  };

  const handleDownloadAll = () => {
    const generatedFiles = files.filter((f) => f.status === "done" && f.code);
    if (generatedFiles.length === 0) {
      toast.error("No generated files to download");
      return;
    }

    const content = generatedFiles
      .map((f) => `// ========== ${f.path} ==========\n\n${f.code}\n`)
      .join("\n\n");

    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${structure.projectName || "project"}-files.txt`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    toast.success(`Downloaded ${generatedFiles.length} files`);
  };

  const completedCount = files.filter((f) => f.status === "done").length;
  const totalCount = files.length;

  const StatusIcon = ({ status }: { status: ParsedFile["status"] }) => {
    switch (status) {
      case "generating":
        return <Loader2 size={14} className="animate-spin text-blue-500" />;
      case "done":
        return <Check size={14} className="text-green-500" />;
      case "error":
        return <AlertCircle size={14} className="text-red-500" />;
      default:
        return <FileCode size={14} className="text-text-secondary" />;
    }
  };

  return (
    <>
      {/* Full width container */}
      <div className="max-w-4xl border border-border rounded-lg overflow-hidden bg-surface shadow-sm">
        {/* Header with clear title */}
        <div className="px-4 py-3 bg-gradient-to-r from-purple-600 to-blue-600 text-white">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Hammer size={20} />
              <div>
                <h3 className="font-bold text-base">PROJECT BUILDER</h3>
                <p className="text-xs text-white/80">
                  {structure.projectName || "Project"} • {structure.tech || ""}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium">
                {completedCount}/{totalCount} generated
              </span>
              {completedCount > 0 && (
                <button
                  onClick={handleDownloadAll}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-white/20 hover:bg-white/30 rounded-lg transition-colors"
                  title="Download all generated files"
                >
                  <Download size={14} />
                  Download All
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Files Section */}
        <div className="border-b border-border">
          <button
            onClick={() => toggleSection("files")}
            className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-panel transition-colors"
          >
            {expandedSections.has("files") ? (
              <ChevronDown size={16} />
            ) : (
              <ChevronRight size={16} />
            )}
            <FileCode size={16} className="text-blue-500" />
            <span className="font-medium text-sm">Files ({totalCount})</span>
            <span className="ml-auto text-xs text-text-secondary">
              Click file to generate code
            </span>
          </button>

          {expandedSections.has("files") && (
            <div className="px-3 pb-3 max-h-80 overflow-y-auto">
              <div className="grid gap-1">
                {files.map((file) => (
                  <div
                    key={file.number}
                    onClick={() => handleFileClick(file)}
                    className={`
                      flex items-center gap-2 py-2 px-3 rounded-lg group transition-all
                      ${
                        file.status === "done"
                          ? "cursor-pointer bg-green-900/30 hover:bg-green-900/40 border border-green-700"
                          : "hover:bg-panel border border-transparent"
                      }
                    `}
                  >
                    <StatusIcon status={file.status} />
                    <span className="text-sm font-mono text-text-primary flex-1 truncate">
                      {file.path}
                    </span>
                    <span className="text-xs text-text-secondary hidden sm:inline truncate max-w-[200px]">
                      {file.description}
                    </span>

                    {/* View button for completed files */}
                    {file.status === "done" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleFileClick(file);
                        }}
                        className="shrink-0 p-1.5 rounded-lg text-blue-500 hover:bg-blue-100 transition-all"
                        title="View code"
                      >
                        <Eye size={14} />
                      </button>
                    )}

                    {/* Download button for completed files */}
                    {file.status === "done" && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDownloadFile(file);
                        }}
                        className="shrink-0 p-1.5 rounded-lg text-green-500 hover:bg-green-100 transition-all"
                        title="Download file"
                      >
                        <Download size={14} />
                      </button>
                    )}

                    {/* Generate button */}
                    {file.status !== "done" && (
                      <button
                        onClick={(e) => handleGenerateFile(file, e)}
                        disabled={
                          file.status === "generating" ||
                          generatingFile !== null
                        }
                        className={`
                          shrink-0 flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium transition-all
                          ${
                            file.status === "generating"
                              ? "bg-blue-100 text-blue-600"
                              : file.status === "error"
                              ? "bg-red-100 text-red-600 hover:bg-red-200"
                              : "bg-blue-500 text-white hover:bg-blue-600 opacity-0 group-hover:opacity-100"
                          }
                        `}
                      >
                        {file.status === "generating" ? (
                          <>
                            <Loader2 size={12} className="animate-spin" />
                            Generating...
                          </>
                        ) : file.status === "error" ? (
                          <>
                            <Play size={12} />
                            Retry
                          </>
                        ) : (
                          <>
                            <Play size={12} />
                            Generate
                          </>
                        )}
                      </button>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Setup Commands Section */}
        {structure.setupCommands.length > 0 && (
          <div className="border-b border-border">
            <button
              onClick={() => toggleSection("commands")}
              className="w-full px-4 py-2.5 flex items-center gap-2 hover:bg-panel transition-colors"
            >
              {expandedSections.has("commands") ? (
                <ChevronDown size={16} />
              ) : (
                <ChevronRight size={16} />
              )}
              <Terminal size={16} className="text-green-500" />
              <span className="font-medium text-sm">
                Setup Commands ({structure.setupCommands.length})
              </span>
            </button>

            {expandedSections.has("commands") && (
              <div className="px-3 pb-3">
                <div className="bg-[#1e1e2e] rounded-lg p-3 font-mono text-xs text-[#cdd6f4] overflow-x-auto max-h-40">
                  {structure.setupCommands.map((cmd, i) => (
                    <div key={i} className="py-0.5 whitespace-nowrap">
                      <span className="text-green-400">$</span> {cmd}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Code Preview Modal */}
      {viewingFile && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
          onClick={() => setViewingFile(null)}
        >
          <div
            className="bg-surface rounded-lg shadow-xl max-w-4xl w-full max-h-[85vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-4 py-3 border-b border-border flex items-center justify-between bg-panel rounded-t-lg">
              <div className="flex items-center gap-2">
                <FileCode size={20} className="text-blue-500" />
                <span className="font-mono text-sm font-medium">
                  {viewingFile.path}
                </span>
              </div>
              <div className="flex items-center gap-1">
                <button
                  onClick={handleCopyCode}
                  className="p-2 hover:bg-surface rounded-lg transition-colors text-text-secondary hover:text-text-primary"
                  title="Copy code"
                >
                  <Copy size={18} />
                </button>
                <button
                  onClick={() => handleDownloadFile(viewingFile)}
                  className="p-2 hover:bg-surface rounded-lg transition-colors text-text-secondary hover:text-text-primary"
                  title="Download file"
                >
                  <Download size={18} />
                </button>
                <button
                  onClick={() => setViewingFile(null)}
                  className="p-2 hover:bg-surface rounded-lg transition-colors text-text-secondary hover:text-text-primary"
                  title="Close"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* Modal Content - Code */}
            <div className="flex-1 overflow-auto p-4">
              <pre className="bg-[#1e1e2e] text-[#cdd6f4] p-4 rounded-lg overflow-x-auto text-sm font-mono leading-relaxed">
                <code>{viewingFile.code}</code>
              </pre>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

export default ProjectStructureView;
