// src/components/Settings/GitIntegrationPanel.tsx
import React, { useState } from "react";
import {
  Link2,
  RefreshCw,
  Link2Off,
  Check,
  AlertCircle,
  Loader2,
  Clock,
  FolderGit2,
} from "lucide-react";
import api from "../../services/api";
import { toast } from "../../store/toastStore";
import type {
  Project,
  GitLinkResponse,
  GitSyncResponse,
} from "../../types/projects";

interface GitIntegrationPanelProps {
  project: Project;
  onProjectUpdated: () => void;
}

const GitIntegrationPanel: React.FC<GitIntegrationPanelProps> = ({
  project,
  onProjectUpdated,
}) => {
  const [gitUrl, setGitUrl] = useState("");
  const [isLinking, setIsLinking] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);
  const [isUnlinking, setIsUnlinking] = useState(false);

  const isLinked = !!project.git_url;
  const isSynced = project.git_sync_status === "synced";
  const isError = project.git_sync_status === "error";
  const isSyncingState = project.git_sync_status === "syncing";

  // Link Git Repository
  const handleLink = async () => {
    if (!gitUrl.trim()) {
      toast.error("Please enter a Git URL");
      return;
    }

    setIsLinking(true);
    try {
      const response = await api.patch<GitLinkResponse>(
        `/projects/${project.id}/git`,
        { git_url: gitUrl.trim() }
      );

      if (response.data.success) {
        toast.success("Repository linked successfully!");
        onProjectUpdated();
        setGitUrl("");
      }
    } catch (error: any) {
      const message =
        error.response?.data?.detail || "Failed to link repository";
      toast.error(message);
    } finally {
      setIsLinking(false);
    }
  };

  // Sync Git Structure
  const handleSync = async () => {
    setIsSyncing(true);
    try {
      const response = await api.post<GitSyncResponse>(
        `/projects/${project.id}/sync-git`
      );

      if (response.data.success) {
        const { files_count, message } = response.data;
        toast.success(message || `Synced ${files_count} files!`);
        onProjectUpdated();
      }
    } catch (error: any) {
      const message =
        error.response?.data?.detail || "Failed to sync repository";
      toast.error(message);
    } finally {
      setIsSyncing(false);
    }
  };

  // Unlink Git Repository
  const handleUnlink = async () => {
    if (!confirm("Are you sure you want to unlink this repository?")) {
      return;
    }

    setIsUnlinking(true);
    try {
      await api.delete(`/projects/${project.id}/git`);
      toast.success("Repository unlinked");
      onProjectUpdated();
    } catch (error: any) {
      const message =
        error.response?.data?.detail || "Failed to unlink repository";
      toast.error(message);
    } finally {
      setIsUnlinking(false);
    }
  };

  // Format date
  const formatDate = (dateStr: string | null | undefined) => {
    if (!dateStr) return "Never";
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now.getTime() - date.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    const minutes = Math.floor(diff / (1000 * 60));

    if (hours < 1) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
    if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
    const days = Math.floor(hours / 24);
    return `${days} day${days === 1 ? "" : "s"} ago`;
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2 mb-2">
          <FolderGit2 className="w-5 h-5 text-primary" />
          <h3 className="text-lg font-semibold text-text-primary">
            Git Integration
          </h3>
        </div>
        <p className="text-sm text-text-secondary">
          Link your GitHub repository to enable smart context and reduce token
          usage by 95%
        </p>
      </div>

      {/* Not Linked State */}
      {!isLinked && (
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-text-primary mb-2">
              Repository URL
            </label>
            <input
              type="text"
              value={gitUrl}
              onChange={(e) => setGitUrl(e.target.value)}
              placeholder="https://github.com/user/repo.git"
              className="w-full px-4 py-2 bg-surface border border-border rounded-lg text-text-primary placeholder:text-text-secondary focus:outline-none focus:border-primary transition"
            />
            <div className="mt-2 text-xs text-text-secondary space-y-1">
              <p>Supported formats:</p>
              <p className="font-mono">• https://github.com/user/repo.git</p>
              <p className="font-mono">• git@github.com:user/repo.git</p>
              <p className="font-mono">• github.com/user/repo</p>
            </div>
          </div>

          <button
            onClick={handleLink}
            disabled={isLinking || !gitUrl.trim()}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
          >
            {isLinking ? (
              <>
                <Loader2 size={18} className="animate-spin" />
                Linking...
              </>
            ) : (
              <>
                <Link2 size={18} />
                Link Repository
              </>
            )}
          </button>

          {/* Benefits */}
          <div className="mt-6 p-4 bg-primary/5 border border-primary/20 rounded-lg">
            <p className="text-sm font-medium text-primary mb-2">
              💡 Benefits:
            </p>
            <ul className="text-xs text-text-secondary space-y-1">
              <li>• AI knows your complete project structure</li>
              <li>• 95% reduction in token usage</li>
              <li>• Save money on API costs</li>
            </ul>
          </div>
        </div>
      )}

      {/* Linked State */}
      {isLinked && (
        <div className="space-y-4">
          {/* Repository Info */}
          <div className="p-4 bg-surface border border-border rounded-lg">
            <div className="flex items-start justify-between mb-3">
              <div className="flex items-center gap-2">
                <Link2 size={16} className="text-primary" />
                <span className="text-sm font-medium text-text-primary">
                  Repository
                </span>
              </div>
              <span className="px-2 py-1 text-xs font-medium bg-primary/10 text-primary rounded">
                Linked
              </span>
            </div>
            <p className="text-sm text-text-primary font-mono bg-panel px-3 py-2 rounded border border-border break-all">
              {project.git_url}
            </p>
          </div>

          {/* Sync Status */}
          <div className="p-4 bg-surface border border-border rounded-lg">
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-text-primary">
                Sync Status
              </span>
              {isSynced && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-success">
                  <Check size={14} />
                  Synced
                </div>
              )}
              {isError && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-error">
                  <AlertCircle size={14} />
                  Error
                </div>
              )}
              {isSyncingState && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-primary">
                  <Loader2 size={14} className="animate-spin" />
                  Syncing...
                </div>
              )}
              {!isSynced && !isError && !isSyncingState && (
                <div className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
                  <Clock size={14} />
                  Not synced
                </div>
              )}
            </div>

            <div className="text-xs text-text-secondary">
              Last sync: {formatDate(project.git_updated_at)}
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3">
            <button
              onClick={handleSync}
              disabled={isSyncing || isSyncingState}
              className="flex-1 flex items-center justify-center gap-2 px-4 py-2.5 bg-primary text-white rounded-lg hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
            >
              {isSyncing ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Syncing...
                </>
              ) : (
                <>
                  <RefreshCw size={16} />
                  Sync Again
                </>
              )}
            </button>

            <button
              onClick={handleUnlink}
              disabled={isUnlinking}
              className="flex items-center justify-center gap-2 px-4 py-2.5 bg-surface border border-error/30 text-error rounded-lg hover:bg-error/10 disabled:opacity-50 disabled:cursor-not-allowed transition font-medium"
            >
              {isUnlinking ? (
                <>
                  <Loader2 size={16} className="animate-spin" />
                  Unlinking...
                </>
              ) : (
                <>
                  <Link2Off size={16} />
                  Unlink
                </>
              )}
            </button>
          </div>

          {/* Info about synced files */}
          {isSynced && project.git_updated_at && (
            <div className="mt-4 p-3 bg-success/5 border border-success/20 rounded-lg">
              <p className="text-xs text-success">
                ✅ Repository structure synced successfully. AI can now access
                your project files for better context.
              </p>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

export default GitIntegrationPanel;
