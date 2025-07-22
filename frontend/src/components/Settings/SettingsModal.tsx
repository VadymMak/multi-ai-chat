import React, { useState, useMemo } from "react";
import {
  X,
  Sun,
  Moon,
  Monitor,
  Zap,
  Palette,
  Info,
  Key,
  Bell,
  MessageSquare,
  Settings as SettingsIcon,
  Download,
  Upload,
  RotateCcw,
  Folder,
  Bot,
} from "lucide-react";
import { useSettingsStore } from "../../store/settingsStore";
import { toast } from "../../store/toastStore";
import ProjectsTab from "./ProjectsTab";
import AssistantsTab from "./AssistantsTab";
import { APIKeysTab } from "./APIKeysTab";

interface SettingsModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialTab?: TabType;
}

type TabType =
  | "appearance"
  | "apikeys"
  | "projects"
  | "assistants"
  | "notifications"
  | "chat"
  | "advanced";

const SettingsModal: React.FC<SettingsModalProps> = ({
  isOpen,
  onClose,
  initialTab = "appearance",
}) => {
  const [activeTab, setActiveTab] = useState<TabType>(initialTab);

  // Get all settings from store
  const settings = useMemo(
    () => ({
      theme: useSettingsStore.getState().theme,
      fontSize: useSettingsStore.getState().fontSize,
      autoScroll: useSettingsStore.getState().autoScroll,
      soundNotifications: useSettingsStore.getState().soundNotifications,
      showTimestamps: useSettingsStore.getState().showTimestamps,
      compactMode: useSettingsStore.getState().compactMode,
      notifications: useSettingsStore.getState().notifications,
      chat: useSettingsStore.getState().chat,
      advanced: useSettingsStore.getState().advanced,
    }),
    [] // Пустой массив - объект создаётся только один раз
  );

  // Get actions
  const {
    setTheme,
    setFontSize,
    setAutoScroll,
    setSoundNotifications,
    setShowTimestamps,
    setCompactMode,
    updateNotifications,
    updateChat,
    updateAdvanced,
    resetToDefaults,
    exportSettings,
    importSettings,
  } = useSettingsStore();

  if (!isOpen) return null;

  const handleSave = () => {
    toast.success("Settings saved successfully!");
    onClose();
  };

  const handleExport = () => {
    const json = exportSettings();
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `ai-assistant-settings-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Settings exported!");
  };

  const handleImport = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
          const json = e.target?.result as string;
          const success = importSettings(json);
          if (success) {
            toast.success("Settings imported successfully!");
          } else {
            toast.error("Failed to import settings");
          }
        };
        reader.readAsText(file);
      }
    };
    input.click();
  };

  const handleReset = () => {
    if (
      window.confirm("Are you sure you want to reset all settings to defaults?")
    ) {
      resetToDefaults();
      toast.success("Settings reset to defaults");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-full max-w-4xl max-h-[90vh] bg-panel border border-border rounded-2xl shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border bg-surface">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-primary/20 flex items-center justify-center">
              <SettingsIcon className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h2 className="text-xl font-semibold text-text-primary">
                Settings
              </h2>
              <p className="text-xs text-text-secondary">
                Customize your AI Assistant
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-surface transition text-text-secondary hover:text-text-primary"
          >
            <X size={20} />
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-border bg-surface/50 px-6 overflow-x-auto">
          <TabButton
            active={activeTab === "appearance"}
            onClick={() => setActiveTab("appearance")}
            icon={<Palette size={16} />}
            label="Appearance"
          />
          <TabButton
            active={activeTab === "apikeys"}
            onClick={() => setActiveTab("apikeys")}
            icon={<Key size={16} />}
            label="API Keys"
          />
          <TabButton
            active={activeTab === "projects"}
            onClick={() => setActiveTab("projects")}
            icon={<Folder size={16} />}
            label="Projects"
          />
          <TabButton
            active={activeTab === "assistants"}
            onClick={() => setActiveTab("assistants")}
            icon={<Bot size={16} />}
            label="Assistants"
          />
          <TabButton
            active={activeTab === "notifications"}
            onClick={() => setActiveTab("notifications")}
            icon={<Bell size={16} />}
            label="Notifications"
          />
          <TabButton
            active={activeTab === "chat"}
            onClick={() => setActiveTab("chat")}
            icon={<MessageSquare size={16} />}
            label="Chat"
          />
          <TabButton
            active={activeTab === "advanced"}
            onClick={() => setActiveTab("advanced")}
            icon={<Info size={16} />}
            label="Advanced"
          />
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* APPEARANCE TAB */}
          {activeTab === "appearance" && (
            <div className="space-y-6">
              {/* Theme */}
              <Section title="Theme" description="Choose your preferred theme">
                <div className="flex gap-3">
                  <ThemeButton
                    active={settings.theme === "light"}
                    onClick={() => setTheme("light")}
                    icon={<Sun size={18} />}
                    label="Light"
                  />
                  <ThemeButton
                    active={settings.theme === "dark"}
                    onClick={() => setTheme("dark")}
                    icon={<Moon size={18} />}
                    label="Dark"
                  />
                  <ThemeButton
                    active={settings.theme === "auto"}
                    onClick={() => setTheme("auto")}
                    icon={<Monitor size={18} />}
                    label="Auto"
                  />
                </div>
              </Section>

              {/* Font Size */}
              <Section
                title="Font Size"
                description="Adjust the interface font size"
              >
                <Slider
                  min={12}
                  max={18}
                  value={settings.fontSize}
                  onChange={setFontSize}
                  label={`${settings.fontSize}px`}
                  minLabel="12px"
                  maxLabel="18px"
                />
              </Section>

              {/* Display Options */}
              <Section
                title="Display Options"
                description="Customize interface behavior"
              >
                <div className="space-y-3">
                  <Toggle
                    checked={settings.autoScroll}
                    onChange={setAutoScroll}
                    label="Auto-scroll to bottom"
                    description="Automatically scroll to new messages"
                  />
                  <Toggle
                    checked={settings.showTimestamps}
                    onChange={setShowTimestamps}
                    label="Show timestamps"
                    description="Display message timestamps"
                  />
                  <Toggle
                    checked={settings.compactMode}
                    onChange={setCompactMode}
                    label="Compact mode"
                    description="Reduce spacing for more content"
                  />
                </div>
              </Section>
            </div>
          )}

          {/* API KEYS TAB */}
          {activeTab === "apikeys" && <APIKeysTab />}

          {/* PROJECTS TAB */}
          {activeTab === "projects" && <ProjectsTab />}

          {/* ASSISTANTS TAB */}
          {activeTab === "assistants" && <AssistantsTab />}

          {/* NOTIFICATIONS TAB */}
          {activeTab === "notifications" && (
            <div className="space-y-6">
              <Section
                title="Notification Settings"
                description="Configure alerts and notifications"
              >
                <div className="space-y-4">
                  <Toggle
                    checked={settings.notifications.enabled}
                    onChange={(enabled) => updateNotifications({ enabled })}
                    label="Enable notifications"
                    description="Show toast notifications"
                  />

                  <Toggle
                    checked={settings.soundNotifications}
                    onChange={setSoundNotifications}
                    label="Sound notifications"
                    description="Play sound for new messages"
                  />

                  <Slider
                    min={3000}
                    max={10000}
                    step={1000}
                    value={settings.notifications.toastDuration}
                    onChange={(duration) =>
                      updateNotifications({ toastDuration: duration })
                    }
                    label={`Toast Duration: ${
                      settings.notifications.toastDuration / 1000
                    }s`}
                    minLabel="3s"
                    maxLabel="10s"
                    description="How long notifications stay visible"
                  />

                  <Slider
                    min={5}
                    max={50}
                    step={5}
                    value={settings.notifications.balanceThreshold}
                    onChange={(threshold) =>
                      updateNotifications({ balanceThreshold: threshold })
                    }
                    label={`Balance Alert Threshold: $${settings.notifications.balanceThreshold}`}
                    minLabel="$5"
                    maxLabel="$50"
                    description="Show warning when balance falls below this amount"
                  />
                </div>
              </Section>
            </div>
          )}

          {/* CHAT TAB */}
          {activeTab === "chat" && (
            <div className="space-y-6">
              <Section
                title="Chat Preferences"
                description="Customize chat behavior"
              >
                <div className="space-y-3">
                  <Toggle
                    checked={settings.chat.autoScroll}
                    onChange={(autoScroll) => updateChat({ autoScroll })}
                    label="Auto-scroll in chat"
                    description="Automatically scroll to new messages"
                  />
                  <Toggle
                    checked={settings.chat.showTimestamps}
                    onChange={(showTimestamps) =>
                      updateChat({ showTimestamps })
                    }
                    label="Show message timestamps"
                    description="Display time for each message"
                  />
                  <Toggle
                    checked={settings.chat.enterToSend}
                    onChange={(enterToSend) => updateChat({ enterToSend })}
                    label="Enter to send"
                    description="Press Enter to send (Ctrl+Enter for new line)"
                  />
                </div>
              </Section>

              <Section
                title="Message Formatting"
                description="Text display options"
              >
                <div className="flex gap-3">
                  <button
                    onClick={() =>
                      updateChat({ messageFormatting: "markdown" })
                    }
                    className={`flex-1 px-4 py-2 rounded-lg border transition text-sm font-medium ${
                      settings.chat.messageFormatting === "markdown"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-surface text-text-secondary hover:border-primary/50"
                    }`}
                  >
                    Markdown
                  </button>
                  <button
                    onClick={() => updateChat({ messageFormatting: "plain" })}
                    className={`flex-1 px-4 py-2 rounded-lg border transition text-sm font-medium ${
                      settings.chat.messageFormatting === "plain"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-surface text-text-secondary hover:border-primary/50"
                    }`}
                  >
                    Plain Text
                  </button>
                </div>
              </Section>

              <Section
                title="Code Theme"
                description="Syntax highlighting theme"
              >
                <div className="flex gap-3">
                  <button
                    onClick={() => updateChat({ codeTheme: "dark" })}
                    className={`flex-1 px-4 py-2 rounded-lg border transition text-sm font-medium ${
                      settings.chat.codeTheme === "dark"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-surface text-text-secondary hover:border-primary/50"
                    }`}
                  >
                    Dark
                  </button>
                  <button
                    onClick={() => updateChat({ codeTheme: "light" })}
                    className={`flex-1 px-4 py-2 rounded-lg border transition text-sm font-medium ${
                      settings.chat.codeTheme === "light"
                        ? "border-primary bg-primary/10 text-primary"
                        : "border-border bg-surface text-text-secondary hover:border-primary/50"
                    }`}
                  >
                    Light
                  </button>
                </div>
              </Section>
            </div>
          )}

          {/* ADVANCED TAB */}
          {activeTab === "advanced" && (
            <div className="space-y-6">
              <Section
                title="Advanced Settings"
                description="Developer and power user options"
              >
                <div className="space-y-3">
                  <Toggle
                    checked={settings.advanced.debug}
                    onChange={(debug) => updateAdvanced({ debug })}
                    label="Debug mode"
                    description="Show detailed logs in console"
                  />
                  <Toggle
                    checked={settings.advanced.enableCache}
                    onChange={(enableCache) => updateAdvanced({ enableCache })}
                    label="Enable caching"
                    description="Cache API responses for better performance"
                  />
                  <Toggle
                    checked={settings.advanced.autoSaveChats}
                    onChange={(autoSaveChats) =>
                      updateAdvanced({ autoSaveChats })
                    }
                    label="Auto-save conversations"
                    description="Automatically save chat history"
                  />
                </div>
              </Section>

              <Section
                title="Data Management"
                description="Import, export, and reset settings"
              >
                <div className="grid grid-cols-3 gap-3">
                  <button
                    onClick={handleExport}
                    className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-border bg-surface text-text-primary hover:border-primary/50 transition text-sm font-medium"
                  >
                    <Download size={16} />
                    Export
                  </button>
                  <button
                    onClick={handleImport}
                    className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-border bg-surface text-text-primary hover:border-primary/50 transition text-sm font-medium"
                  >
                    <Upload size={16} />
                    Import
                  </button>
                  <button
                    onClick={handleReset}
                    className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg border border-error/30 bg-error/10 text-error hover:bg-error/20 transition text-sm font-medium"
                  >
                    <RotateCcw size={16} />
                    Reset
                  </button>
                </div>
              </Section>

              <Section title="About" description="Application information">
                <div className="text-center py-6">
                  <div className="w-16 h-16 mx-auto rounded-full bg-primary/20 flex items-center justify-center mb-4">
                    <Zap className="w-8 h-8 text-primary" />
                  </div>
                  <h3 className="text-lg font-semibold text-text-primary mb-1">
                    AI Assistant IDE
                  </h3>
                  <p className="text-sm text-text-secondary mb-1">
                    Version 1.0.0
                  </p>
                  <p className="text-xs text-text-secondary">
                    Built with React + FastAPI
                  </p>
                  <p className="text-xs text-text-secondary mt-3">
                    Made with ❤️ by VadymMak
                  </p>
                </div>
              </Section>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border bg-surface">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-text-secondary hover:text-text-primary transition"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            className="px-6 py-2 text-sm font-medium bg-primary text-white rounded-lg hover:opacity-90 transition"
          >
            Save Changes
          </button>
        </div>
      </div>
    </div>
  );
};

// ========== HELPER COMPONENTS ==========

const TabButton: React.FC<{
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}> = ({ active, onClick, icon, label }) => (
  <button
    onClick={onClick}
    className={`px-4 py-3 text-sm font-medium transition border-b-2 whitespace-nowrap ${
      active
        ? "border-primary text-primary"
        : "border-transparent text-text-secondary hover:text-text-primary"
    }`}
  >
    <div className="flex items-center gap-2">
      {icon}
      {label}
    </div>
  </button>
);

const Section: React.FC<{
  title: string;
  description?: string;
  children: React.ReactNode;
}> = ({ title, description, children }) => (
  <div>
    <div className="mb-4">
      <h3 className="text-base font-semibold text-text-primary">{title}</h3>
      {description && (
        <p className="text-xs text-text-secondary mt-1">{description}</p>
      )}
    </div>
    {children}
  </div>
);

const ThemeButton: React.FC<{
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}> = ({ active, onClick, icon, label }) => (
  <button
    onClick={onClick}
    className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-lg border transition ${
      active
        ? "border-primary bg-primary/10 text-primary"
        : "border-border bg-surface text-text-secondary hover:border-primary/50"
    }`}
  >
    {icon}
    {label}
  </button>
);

const Slider: React.FC<{
  min: number;
  max: number;
  step?: number;
  value: number;
  onChange: (value: number) => void;
  label: string;
  minLabel: string;
  maxLabel: string;
  description?: string;
}> = ({
  min,
  max,
  step,
  value,
  onChange,
  label,
  minLabel,
  maxLabel,
  description,
}) => (
  <div>
    <label className="block text-sm font-medium text-text-primary mb-3">
      {label}
    </label>
    <input
      type="range"
      min={min}
      max={max}
      step={step}
      value={value}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full h-2 bg-surface rounded-lg appearance-none cursor-pointer accent-primary"
    />
    <div className="flex justify-between text-xs text-text-secondary mt-1">
      <span>{minLabel}</span>
      <span>{maxLabel}</span>
    </div>
    {description && (
      <p className="text-xs text-text-secondary mt-2">{description}</p>
    )}
  </div>
);

const Toggle: React.FC<{
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  description: string;
}> = ({ checked, onChange, label, description }) => (
  <label className="flex items-center gap-3 cursor-pointer group">
    <input
      type="checkbox"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      className="w-5 h-5 rounded border-border bg-surface accent-primary cursor-pointer"
    />
    <div className="flex-1">
      <div className="text-sm font-medium text-text-primary group-hover:text-primary transition">
        {label}
      </div>
      <div className="text-xs text-text-secondary">{description}</div>
    </div>
  </label>
);

export default SettingsModal;
