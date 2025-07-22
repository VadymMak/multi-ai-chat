// File: src/components/Chat/AuditLogsPanel.tsx
import React, { useEffect, useState } from "react";
import { getAuditLogs } from "../../services/auditApi";
import { useMemoryStore } from "../../store/memoryStore";
import { useProjectStore } from "../../store/projectStore";
import type { AuditLogEntry } from "../../types/audit";

const AuditLogsPanel: React.FC = () => {
  const role = useMemoryStore((s) => s.role);
  const roleId = typeof role?.id === "number" ? role.id : null;
  const projectId = useProjectStore((s) => s.projectId ?? null);

  const [logs, setLogs] = useState<AuditLogEntry[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchLogs = async () => {
      if (!roleId || !projectId) return;
      try {
        setIsLoading(true);
        const result = await getAuditLogs({
          role_id: roleId,
          project_id: projectId,
        });
        if (Array.isArray(result)) {
          setLogs(result);
        } else {
          setLogs([]);
        }
      } catch (err) {
        console.error("❌ Failed to fetch audit logs:", err);
        setLogs([]);
      } finally {
        setIsLoading(false);
      }
    };
    fetchLogs();
  }, [roleId, projectId]);

  if (!roleId || !projectId) {
    return (
      <div className="text-gray-400 text-sm">
        Please select a role and project to view audit logs.
      </div>
    );
  }

  return (
    // NOTE: no overflow here — parent sidebar owns the scroll
    <div className="space-y-3 text-sm">
      <div className="text-xs text-gray-500">
        Showing logs filtered by current role and project.
      </div>

      {isLoading ? (
        <div className="text-gray-500">Loading audit logs…</div>
      ) : logs.length === 0 ? (
        <div className="text-gray-400">
          No audit logs found for this context.
        </div>
      ) : (
        <ul className="space-y-2">
          {logs.map((log) => (
            <li
              key={log.id}
              className="p-2 bg-white border border-gray-200 rounded shadow-sm"
            >
              <div className="text-gray-800 font-medium">
                {log.model_version} → {log.provider}
              </div>
              <div className="text-xs text-gray-500">
                {new Date(log.timestamp).toLocaleString()}
              </div>
              <div className="text-xs text-gray-600 mt-1">
                role: {log.role_id}, project: {log.project_id}, session:{" "}
                {log.chat_session_id || "—"}
              </div>
              {log.query && (
                <div className="mt-1 text-xs text-gray-700 italic line-clamp-2">
                  "{log.query}"
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default AuditLogsPanel;
