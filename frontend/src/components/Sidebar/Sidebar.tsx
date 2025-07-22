import React, { useState, useEffect } from "react";
import {
  Search,
  ChevronDown,
  Plus,
  Settings,
  Trash2,
  Clock,
} from "lucide-react";
import ProjectSelector from "../../features/aiConversation/ProjectSelector";
import AssistantSelector from "../../features/aiConversation/AssistantSelector";
import SessionControls from "../Chat/SessionControls";
import { useChatStore } from "../../store/chatStore";
import { useRoleStore } from "../../store/roleStore";
import api from "../../services/api";
import SettingsModal from "../Settings/SettingsModal";
import Skeleton from "../Shared/Skeleton";
import { toast } from "../../store/toastStore";

interface SessionInfo {
  chat_session_id: string;
  role_id: number;
  project_id: number;
  lastMessage?: string;
  timestamp?: string;
  messageCount?: number;
}

interface SidebarProps {
  // Add any props if needed later
}

// Функция для группировки sessions по датам
function groupSessionsByDate(sessions: SessionInfo[]) {
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);
  const lastWeek = new Date(today);
  lastWeek.setDate(lastWeek.getDate() - 7);

  const groups = {
    today: [] as SessionInfo[],
    yesterday: [] as SessionInfo[],
    lastWeek: [] as SessionInfo[],
    older: [] as SessionInfo[],
  };

  sessions.forEach((session) => {
    const sessionDate = session.timestamp
      ? new Date(session.timestamp)
      : new Date();

    if (sessionDate >= today) {
      groups.today.push(session);
    } else if (sessionDate >= yesterday) {
      groups.yesterday.push(session);
    } else if (sessionDate >= lastWeek) {
      groups.lastWeek.push(session);
    } else {
      groups.older.push(session);
    }
  });

  return groups;
}

// Генерация названия session из первого сообщения
function generateSessionTitle(lastMessage?: string): string {
  if (!lastMessage) return "New conversation";

  // Убираем code blocks
  let text = lastMessage.replace(/```[\s\S]*?```/g, "");

  // Убираем markdown символы
  text = text.replace(/[#*_`]/g, "");

  // Берем первые 30 символов (короче!)
  text = text.trim().substring(0, 30);

  // Обрезаем по последнему пробелу чтобы не резать слова
  const lastSpace = text.lastIndexOf(" ");
  if (lastSpace > 20) {
    text = text.substring(0, lastSpace);
  }

  return text || "New conversation";
}

// Format timestamp
const formatTimestamp = (timestamp?: string) => {
  if (!timestamp) return "Just now";
  return timestamp;
};

interface SessionItemProps {
  session: SessionInfo;
  isActive: boolean;
  onSelect: () => void;
  onDelete: () => void;
}

const SessionItem: React.FC<SessionItemProps> = ({
  session,
  isActive,
  onSelect,
  onDelete,
}) => {
  const title = generateSessionTitle(session.lastMessage);

  return (
    <div
      className={`w-full px-3 py-2 rounded hover:bg-surface group transition cursor-pointer ${
        isActive ? "bg-surface border-l-2 border-primary" : ""
      }`}
      onClick={onSelect}
    >
      <div className="flex items-center justify-between gap-3">
        {/* Left side - content with max width */}
        <div className="flex-1 min-w-0 max-w-[180px]">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-sm flex-shrink-0">💬</span>
            <p className="text-sm text-text-primary truncate font-medium">
              {title}
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs text-text-secondary truncate">
            <Clock size={10} className="flex-shrink-0" />
            <span>{formatTimestamp(session.timestamp)}</span>
            {session.messageCount !== undefined && (
              <>
                <span>•</span>
                <span>{session.messageCount} msgs</span>
              </>
            )}
          </div>
        </div>

        {/* Right side - delete button always visible space */}
        <div className="flex-shrink-0 w-8 flex items-center justify-center">
          {isActive && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete();
              }}
              className="opacity-0 group-hover:opacity-100 p-1.5 hover:bg-error/10 rounded transition"
              title="Clear session"
              type="button"
            >
              <Trash2 size={14} className="text-error" />
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

const Sidebar: React.FC<SidebarProps> = () => {
  const [searchQuery, setSearchQuery] = useState("");
  const [projectsExpanded, setProjectsExpanded] = useState(true);
  const [sessionsExpanded, setSessionsExpanded] = useState(true);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"projects" | "assistants">(
    "projects"
  );

  // Store hooks
  const clearMessages = useChatStore.use.clearMessages();
  const messages = useChatStore.use.messages();
  const chatSessionId = useChatStore.use.chatSessionId();
  const lastSessionMarker = useChatStore.use.lastSessionMarker();
  const loadOrInitSessionForRoleProject =
    useChatStore.use.loadOrInitSessionForRoleProject();

  const roles = useRoleStore((s) => s.roles);

  // Get current role from lastSessionMarker
  const currentRoleId = lastSessionMarker?.roleId;
  const currentProjectId = lastSessionMarker?.projectId;

  // Fetch sessions for current context
  useEffect(() => {
    if (!currentRoleId || !currentProjectId) return;

    const fetchSessions = async () => {
      setIsLoadingSessions(true);
      try {
        // For now, we'll just show the current session
        // In a full implementation, you might fetch multiple sessions from backend
        const response = await api.get("/chat/last-session-by-role", {
          params: {
            role_id: currentRoleId,
            project_id: currentProjectId,
            limit: 20,
          },
        });

        if (response.data?.chat_session_id) {
          const lastMsg =
            response.data.messages?.[response.data.messages.length - 1];
          setSessions([
            {
              chat_session_id: response.data.chat_session_id,
              role_id: currentRoleId,
              project_id: currentProjectId,
              lastMessage:
                lastMsg?.text?.substring(0, 50) || "New conversation",
              timestamp: "Active now",
              messageCount: response.data.messages?.length || 0,
            },
          ]);
        }
      } catch (error) {
        console.error("Failed to fetch sessions:", error);
        setSessions([]);
      } finally {
        setIsLoadingSessions(false);
      }
    };

    fetchSessions();
  }, [currentRoleId, currentProjectId, chatSessionId]);

  // Handle clearing current session
  const handleClearSession = () => {
    if (
      window.confirm(
        "Are you sure you want to clear the current session? This cannot be undone."
      )
    ) {
      clearMessages();
      toast.success("Session cleared!");
    }
  };

  // Handle creating new session
  const handleNewSession = async () => {
    if (!currentRoleId || !currentProjectId) {
      toast.error("Please select a role and project first");
      return;
    }

    try {
      clearMessages();
      await loadOrInitSessionForRoleProject(currentRoleId, currentProjectId);
      toast.success("New session created!");
    } catch (error) {
      console.error("Failed to create new session:", error);
      toast.error("Failed to create new session");
    }
  };

  // Handle session selection
  const handleSessionSelect = async (session: SessionInfo) => {
    if (session.chat_session_id === chatSessionId) return; // Already selected

    try {
      await loadOrInitSessionForRoleProject(
        session.role_id,
        session.project_id
      );
    } catch (error) {
      console.error("Failed to load session:", error);
      toast.error("Failed to load session");
    }
  };

  // Get current role name
  const currentRole = roles.find((r) => r.id === currentRoleId);
  const currentRoleName = currentRole?.name || "Unknown";

  // Filter sessions by search query
  const filteredSessions = sessions.filter((session) =>
    session.lastMessage?.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <>
      <aside className="w-72 bg-panel border-r border-border flex flex-col">
        {/* 1. Search Bar */}
        <div className="p-4 border-b border-border">
          <div className="relative">
            <Search className="absolute left-3 top-2.5 w-4 h-4 text-text-secondary" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search sessions..."
              className="w-full px-3 py-2 pl-9 text-sm bg-surface border border-border rounded focus:outline-none focus:border-primary text-text-primary placeholder:text-text-secondary"
            />
          </div>
        </div>

        {/* 2. Projects Section */}
        <div className="border-b border-border">
          <button
            onClick={() => setProjectsExpanded(!projectsExpanded)}
            className="w-full px-4 py-3 flex items-center justify-between hover:bg-surface transition"
          >
            <span className="text-sm font-medium text-text-primary flex items-center gap-2">
              📁 Projects
            </span>
            <ChevronDown
              size={16}
              className={`text-text-secondary transition-transform ${
                projectsExpanded ? "rotate-180" : ""
              }`}
            />
          </button>

          {projectsExpanded && (
            <div className="pb-2">
              <div className="px-4">
                <ProjectSelector />
                <button
                  onClick={() => {
                    setSettingsTab("projects");
                    setIsSettingsOpen(true);
                  }}
                  className="w-full mt-2 text-xs text-blue-400 hover:text-blue-300 text-left transition"
                >
                  💡 Manage projects in Settings
                </button>
              </div>

              {/* Assistant/Role Selector */}
              <div className="px-4 mt-3">
                <label className="text-xs font-medium text-text-secondary mb-1 block">
                  🤖 Assistant
                </label>
                <AssistantSelector />
                <button
                  onClick={() => {
                    setSettingsTab("assistants");
                    setIsSettingsOpen(true);
                  }}
                  className="w-full mt-2 text-xs text-blue-400 hover:text-blue-300 text-left transition"
                >
                  💡 Manage assistants in Settings
                </button>
              </div>

              <button
                onClick={handleNewSession}
                className="w-full px-6 py-2 mt-3 text-left text-sm text-primary hover:bg-surface flex items-center gap-2 transition"
              >
                <Plus size={14} />
                New Session
              </button>
            </div>
          )}
        </div>

        {/* 3. Sessions Section */}
        <div className="flex-1 overflow-y-auto border-b border-border">
          <button
            onClick={() => setSessionsExpanded(!sessionsExpanded)}
            className="sticky top-0 bg-panel w-full px-4 py-3 flex items-center justify-between hover:bg-surface transition border-b border-border z-10"
          >
            <span className="text-sm font-medium text-text-primary flex items-center gap-2">
              💬 Chat Sessions
              {messages.length > 0 && (
                <span className="text-xs text-text-secondary">
                  ({messages.length})
                </span>
              )}
            </span>
            <ChevronDown
              size={16}
              className={`text-text-secondary transition-transform ${
                sessionsExpanded ? "rotate-180" : ""
              }`}
            />
          </button>

          {sessionsExpanded && (
            <div className="py-2">
              <div className="px-4">
                {/* Current context info */}
                {currentRoleId && currentProjectId && (
                  <div className="mb-3 p-2 bg-surface/50 rounded text-xs text-text-secondary">
                    <div className="flex items-center gap-1">
                      <span className="font-medium">Role:</span>
                      <span>{currentRoleName}</span>
                    </div>
                    <div className="flex items-center gap-1 mt-1">
                      <span className="font-medium">Project:</span>
                      <span>ID {currentProjectId}</span>
                    </div>
                  </div>
                )}

                {isLoadingSessions ? (
                  <div className="space-y-2 px-4">
                    <Skeleton className="h-16 w-full" count={3} />
                  </div>
                ) : filteredSessions.length === 0 ? (
                  <div className="text-center py-8">
                    <p className="text-sm text-text-secondary">
                      {searchQuery ? "No matching sessions" : "No sessions yet"}
                    </p>
                    <button
                      onClick={handleNewSession}
                      className="mt-3 px-4 py-2 text-sm bg-primary text-white rounded hover:bg-primary/90 transition"
                    >
                      Start New Chat
                    </button>
                  </div>
                ) : (
                  <>
                    {(() => {
                      const grouped = groupSessionsByDate(filteredSessions);

                      return (
                        <div className="space-y-4">
                          {/* Today */}
                          {grouped.today.length > 0 && (
                            <div>
                              <h4 className="px-3 py-1 text-xs font-semibold text-text-secondary uppercase tracking-wide">
                                Today
                              </h4>
                              <div className="space-y-1 mt-1">
                                {grouped.today.map((session) => {
                                  const isActive =
                                    session.chat_session_id === chatSessionId;
                                  return (
                                    <SessionItem
                                      key={session.chat_session_id}
                                      session={session}
                                      isActive={isActive}
                                      onSelect={() =>
                                        handleSessionSelect(session)
                                      }
                                      onDelete={handleClearSession}
                                    />
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* Yesterday */}
                          {grouped.yesterday.length > 0 && (
                            <div>
                              <h4 className="px-3 py-1 text-xs font-semibold text-text-secondary uppercase tracking-wide">
                                Yesterday
                              </h4>
                              <div className="space-y-1 mt-1">
                                {grouped.yesterday.map((session) => {
                                  const isActive =
                                    session.chat_session_id === chatSessionId;
                                  return (
                                    <SessionItem
                                      key={session.chat_session_id}
                                      session={session}
                                      isActive={isActive}
                                      onSelect={() =>
                                        handleSessionSelect(session)
                                      }
                                      onDelete={handleClearSession}
                                    />
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* Last 7 days */}
                          {grouped.lastWeek.length > 0 && (
                            <div>
                              <h4 className="px-3 py-1 text-xs font-semibold text-text-secondary uppercase tracking-wide">
                                Last 7 days
                              </h4>
                              <div className="space-y-1 mt-1">
                                {grouped.lastWeek.map((session) => {
                                  const isActive =
                                    session.chat_session_id === chatSessionId;
                                  return (
                                    <SessionItem
                                      key={session.chat_session_id}
                                      session={session}
                                      isActive={isActive}
                                      onSelect={() =>
                                        handleSessionSelect(session)
                                      }
                                      onDelete={handleClearSession}
                                    />
                                  );
                                })}
                              </div>
                            </div>
                          )}

                          {/* Older */}
                          {grouped.older.length > 0 && (
                            <div>
                              <h4 className="px-3 py-1 text-xs font-semibold text-text-secondary uppercase tracking-wide">
                                Older
                              </h4>
                              <div className="space-y-1 mt-1">
                                {grouped.older.map((session) => {
                                  const isActive =
                                    session.chat_session_id === chatSessionId;
                                  return (
                                    <SessionItem
                                      key={session.chat_session_id}
                                      session={session}
                                      isActive={isActive}
                                      onSelect={() =>
                                        handleSessionSelect(session)
                                      }
                                      onDelete={handleClearSession}
                                    />
                                  );
                                })}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })()}
                  </>
                )}

                {/* Advanced session controls (collapsed by default) */}
                <details className="mt-4">
                  <summary className="text-xs text-text-secondary cursor-pointer hover:text-text-primary px-2">
                    Advanced session controls
                  </summary>
                  <div className="mt-2">
                    <SessionControls />
                  </div>
                </details>
              </div>
            </div>
          )}
        </div>

        {/* 5. Footer Buttons */}
        <div className="border-t border-border p-4 space-y-2">
          <button
            onClick={() => {
              setSettingsTab("projects");
              setIsSettingsOpen(true);
            }}
            className="w-full px-4 py-2 text-sm bg-surface hover:bg-surface/80 rounded border border-border flex items-center gap-2 text-text-primary transition"
          >
            <Settings size={16} />
            Settings
          </button>
          <button
            onClick={handleClearSession}
            disabled={messages.length === 0}
            className="w-full px-4 py-2 text-sm bg-surface hover:bg-error/10 text-error rounded border border-error flex items-center gap-2 transition disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-surface"
          >
            <Trash2 size={16} />
            Clear Session ({messages.length})
          </button>
        </div>
      </aside>
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
        initialTab={settingsTab}
      />
    </>
  );
};

export default Sidebar;
