// src/services/fileApi.ts
import api from "./api";
import type { GeneratedFilesResponse } from "../types/projects";

/**
 * File API - Generated files from Project Builder
 */

/** GET /project-builder/projects/{id}/all-generated-files */
export const getGeneratedFiles = async (
  projectId: number
): Promise<GeneratedFilesResponse> => {
  const res = await api.get<GeneratedFilesResponse>(
    `/project-builder/projects/${projectId}/all-generated-files`
  );
  return res.data;
};

/** Download single file to user's computer */
export const downloadFile = (fileName: string, content: string): void => {
  const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};
