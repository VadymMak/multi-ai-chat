import axios from "./axiosInstance";

export const getAuditLogs = async (params?: {
  role_id?: number;
  project_id?: number;
  chat_session_id?: string;
}) => {
  const response = await axios.get("/audit/logs", { params });
  return response.data;
};
