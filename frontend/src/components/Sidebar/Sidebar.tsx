import React, { useState } from "react";
import { Settings, Trash2, LogOut, User, FileText } from "lucide-react";
import ProjectSelector from "../../features/aiConversation/ProjectSelector";
import FilesModal from "../FileViewer/FilesModal";
import { useChatStore } from "../../store/chatStore";
import { useAuthStore } from "../../store/authStore";
import SettingsModal from "../Settings/SettingsModal";
import { toast } from "../../store/toastStore";
import { useProjectStore } from "../../store/projectStore";

interface SidebarProps {
  // Add any props if needed later
}

const Sidebar: React.FC<SidebarProps> = () => {
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isFilesModalOpen, setIsFilesModalOpen] = useState(false);

  // Store hooks
  const clearMessages = useChatStore.use.clearMessages();
  const messages = useChatStore.use.messages();
  const { user, logout } = useAuthStore();
  const projectId = useProjectStore((s) => s.projectId);
  const projectsByRole = useProjectStore((s) => s.projectsByRole);
  const roleId = 1; // Or get from your memory store if needed
  const currentProject =
    projectId && projectsByRole[roleId]
      ? projectsByRole[roleId].find((p) => p.id === projectId)
      : null;

  // Handle clearing current session
  const handleClearChat = () => {
    if (messages.length === 0) {
      toast.info("Chat is already empty");
      return;
    }

    if (
      window.confirm(
        "Are you sure you want to clear the current chat? This cannot be undone."
      )
    ) {
      clearMessages();
      toast.success("Chat cleared!");
    }
  };

  const handleOpenSettings = () => {
    setIsSettingsOpen(true);
  };

  return (
    <>
      <aside className="w-72 bg-panel border-r border-border flex flex-col">
        {/* Header */}
        <div className="p-4 border-b border-border">
          <h2 className="text-lg font-semibold text-text-primary flex items-center gap-2">
            📁 My Projects
          </h2>
          <p className="text-xs text-text-secondary mt-1">
            Select a project to start chatting
          </p>
        </div>

        {/* Projects List - Scrollable */}
        <div className="flex-1 overflow-y-auto p-4">
          <ProjectSelector onOpenSettings={handleOpenSettings} />
        </div>

        {/* Footer Buttons - KEEP ONLY THIS ONE */}
        <div className="border-t border-border p-4 space-y-2">
          <button
            onClick={handleClearChat}
            disabled={messages.length === 0}
            className="w-full px-4 py-2.5 text-sm bg-surface hover:bg-error/10 text-error rounded-lg border border-error/30 hover:border-error flex items-center justify-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-surface disabled:hover:border-error/30"
            title={
              messages.length === 0
                ? "No messages to clear"
                : "Clear current chat"
            }
          >
            <Trash2 size={16} />
            Clear Chat {messages.length > 0 && `(${messages.length})`}
          </button>

          <button
            onClick={() => setIsFilesModalOpen(true)}
            disabled={!projectId}
            className="w-full px-4 py-2.5 text-sm bg-surface hover:bg-primary/10 text-primary rounded-lg border border-primary/30 hover:border-primary flex items-center justify-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-surface disabled:hover:border-primary/30"
            title={
              projectId ? "View generated files" : "Select a project first"
            }
          >
            <FileText size={16} />
            View Files
          </button>

          <button
            onClick={handleOpenSettings}
            className="w-full px-4 py-2.5 text-sm bg-surface hover:bg-surface/80 rounded-lg border border-border hover:border-primary/50 flex items-center justify-center gap-2 text-text-primary transition"
          >
            <Settings size={16} />
            Settings
          </button>
        </div>

        {/* User Info */}
        {user && (
          <div className="border-t border-border p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2 flex-1 min-w-0">
                <User size={16} className="text-text-secondary flex-shrink-0" />
                <span className="text-sm text-text-primary truncate">
                  {user.username}
                </span>
              </div>
              <button
                onClick={logout}
                className="p-1.5 text-text-secondary hover:text-error hover:bg-error/10 rounded transition-colors flex-shrink-0"
                title="Logout"
              >
                <LogOut size={16} />
              </button>
            </div>
            {user.status === "trial" && user.trial_ends_at && (
              <div className="text-xs text-yellow-400">
                Trial:{" "}
                {Math.max(
                  0,
                  Math.ceil(
                    (new Date(user.trial_ends_at).getTime() - Date.now()) /
                      (1000 * 60 * 60 * 24)
                  )
                )}{" "}
                days left
              </div>
            )}
          </div>
        )}
      </aside>

      {/* Modals - KEEP ONLY ONE OF EACH */}
      {projectId && currentProject && (
        <FilesModal
          isOpen={isFilesModalOpen}
          onClose={() => setIsFilesModalOpen(false)}
          projectId={projectId}
          projectName={currentProject.name}
        />
      )}

      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        initialTab="projects"
      />
    </>
  );
};

export default Sidebar;
