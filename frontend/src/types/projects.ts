// src/types/projects.ts
export interface ProjectOption {
  id: number;
  name: string;
  description?: string;
}

export interface Assistant {
  id: number;
  name: string;
  description?: string;
}

export interface Project {
  id: number;
  name: string;
  description?: string;
  assistant?: Assistant;
  assistant_id?: number;
  created_at?: string;
  updated_at?: string;

  // ✅ Git Integration fields (Phase 1)
  git_url?: string | null;
  git_updated_at?: string | null;
  git_sync_status?: "syncing" | "synced" | "error" | null;
}

export interface ProjectCreate {
  name: string;
  description?: string;
  assistant_id: number;
}

export interface ProjectUpdate {
  name?: string;
  description?: string;
}

// ✅ Git Integration API types
export interface GitLinkRequest {
  git_url: string;
}

export interface GitLinkResponse {
  success: boolean;
  git_url: string;
  normalized: boolean;
  message?: string;
}

export interface GitSyncResponse {
  success: boolean;
  files_count: number;
  synced_at: string;
  files_preview?: Array<{ path: string }>;
  message?: string;
}

// ✅ NEW: File Viewer types (Phase 0 - Week 1)
export interface GeneratedFile {
  file_path: string;
  content: string;
  language: string;
  size: number;
}

export interface GeneratedFilesResponse {
  project_id: number;
  project_name: string;
  total_files: number;
  files: GeneratedFile[];
}

export interface FileNode {
  name: string;
  path: string;
  type: "file" | "directory";
  children?: FileNode[];
  file?: GeneratedFile;
}
