import api from "../services/api";

export interface UploadFileRequest {
  file: File;
  roleId: number;
  projectId: number;
  chatSessionId?: string;
  provider?: "openai" | "claude";
}

export interface UploadFileResponse {
  filename: string;
  attachment_id: number;
  size: number;
  file_type: "image" | "document" | "data";
  download_url: string;
  preview: string;
  summary: string;
  chat_session_id: string;
  message_id: number;
}

export const uploadFile = async (
  request: UploadFileRequest
): Promise<UploadFileResponse> => {
  const formData = new FormData();
  formData.append("file", request.file);

  const params = new URLSearchParams({
    role_id: request.roleId.toString(),
    project_id: request.projectId.toString(),
    ...(request.chatSessionId && { chat_session_id: request.chatSessionId }),
    ...(request.provider && { provider: request.provider }),
  });

  const response = await api.post<UploadFileResponse>(
    `/upload?${params.toString()}`,
    formData,
    {
      headers: {
        "Content-Type": "multipart/form-data",
      },
    }
  );

  return response.data;
};

export const getFileDownloadUrl = (attachmentId: number): string => {
  return `${api.defaults.baseURL}/uploads/${attachmentId}`;
};
