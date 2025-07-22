export interface AuditLogEntry {
  id: number;
  timestamp: string;
  provider: string;
  model_version: string;
  action: string;
  query: string;
  role_id: number;
  project_id: string;
  chat_session_id?: string;
}
