/**
 * Settings Store
 * Управление пользовательскими настройками приложения
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SettingsState {
  // ========== APPEARANCE ==========
  theme: "light" | "dark" | "auto";
  fontSize: number;
  autoScroll: boolean;
  soundNotifications: boolean;
  showTimestamps: boolean;
  compactMode: boolean;

  // ========== AI MODEL ==========
  temperature: number;
  maxTokens: number;
  defaultModel: "openai" | "anthropic";

  // ========== API KEYS ==========
  apiKeys: {
    openai: string;
    anthropic: string;
    youtube: string;
  };

  // ========== NOTIFICATIONS ==========
  notifications: {
    enabled: boolean;
    balanceThreshold: number; // Порог предупреждения о балансе ($)
    toastDuration: number; // Длительность toast (ms)
    soundEnabled: boolean;
  };

  // ========== CHAT PREFERENCES ==========
  chat: {
    autoScroll: boolean;
    showTimestamps: boolean;
    codeTheme: "dark" | "light";
    messageFormatting: "markdown" | "plain";
    enterToSend: boolean; // Enter отправляет или Ctrl+Enter
  };

  // ========== ADVANCED ==========
  advanced: {
    debug: boolean;
    enableCache: boolean;
    autoSaveChats: boolean;
  };

  // ========== ACTIONS ==========
  // Appearance
  setTheme: (theme: "light" | "dark" | "auto") => void;
  setFontSize: (size: number) => void;
  setAutoScroll: (enabled: boolean) => void;
  setSoundNotifications: (enabled: boolean) => void;
  setShowTimestamps: (show: boolean) => void;
  setCompactMode: (compact: boolean) => void;

  // Model
  setTemperature: (temp: number) => void;
  setMaxTokens: (tokens: number) => void;
  setDefaultModel: (model: "openai" | "anthropic") => void;

  // API Keys
  updateApiKey: (provider: keyof SettingsState["apiKeys"], key: string) => void;
  clearApiKey: (provider: keyof SettingsState["apiKeys"]) => void;

  // Notifications
  updateNotifications: (
    notifications: Partial<SettingsState["notifications"]>
  ) => void;

  // Chat
  updateChat: (chat: Partial<SettingsState["chat"]>) => void;

  // Advanced
  updateAdvanced: (advanced: Partial<SettingsState["advanced"]>) => void;

  // General
  resetToDefaults: () => void;
  exportSettings: () => string;
  importSettings: (json: string) => boolean;
}

const defaultSettings = {
  // Appearance
  theme: "dark" as const,
  fontSize: 14,
  autoScroll: true,
  soundNotifications: false,
  showTimestamps: true,
  compactMode: false,

  // Model
  temperature: 0.7,
  maxTokens: 2000,
  defaultModel: "openai" as const,

  // API Keys (пустые по умолчанию - пользователь вводит сам)
  apiKeys: {
    openai: "",
    anthropic: "",
    youtube: "",
  },

  // Notifications
  notifications: {
    enabled: true,
    balanceThreshold: 10, // $10
    toastDuration: 5000, // 5 секунд
    soundEnabled: false,
  },

  // Chat
  chat: {
    autoScroll: true,
    showTimestamps: true,
    codeTheme: "dark" as const,
    messageFormatting: "markdown" as const,
    enterToSend: false, // Ctrl+Enter для отправки
  },

  // Advanced
  advanced: {
    debug: false,
    enableCache: true,
    autoSaveChats: true,
  },
};

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set, get) => ({
      ...defaultSettings,

      // ========== APPEARANCE ACTIONS ==========
      setTheme: (theme) => set({ theme }),
      setFontSize: (fontSize) => set({ fontSize }),
      setAutoScroll: (autoScroll) => set({ autoScroll }),
      setSoundNotifications: (soundNotifications) =>
        set({ soundNotifications }),
      setShowTimestamps: (showTimestamps) => set({ showTimestamps }),
      setCompactMode: (compactMode) => set({ compactMode }),

      // ========== MODEL ACTIONS ==========
      setTemperature: (temperature) => set({ temperature }),
      setMaxTokens: (maxTokens) => set({ maxTokens }),
      setDefaultModel: (defaultModel) => set({ defaultModel }),

      // ========== API KEYS ACTIONS ==========
      updateApiKey: (provider, key) =>
        set((state) => ({
          apiKeys: {
            ...state.apiKeys,
            [provider]: key,
          },
        })),

      clearApiKey: (provider) =>
        set((state) => ({
          apiKeys: {
            ...state.apiKeys,
            [provider]: "",
          },
        })),

      // ========== NOTIFICATIONS ACTIONS ==========
      updateNotifications: (notifications) =>
        set((state) => ({
          notifications: {
            ...state.notifications,
            ...notifications,
          },
        })),

      // ========== CHAT ACTIONS ==========
      updateChat: (chat) =>
        set((state) => ({
          chat: {
            ...state.chat,
            ...chat,
          },
        })),

      // ========== ADVANCED ACTIONS ==========
      updateAdvanced: (advanced) =>
        set((state) => ({
          advanced: {
            ...state.advanced,
            ...advanced,
          },
        })),

      // ========== GENERAL ACTIONS ==========
      resetToDefaults: () => set(defaultSettings),

      exportSettings: () => {
        const state = get();
        const exportData = {
          theme: state.theme,
          fontSize: state.fontSize,
          autoScroll: state.autoScroll,
          soundNotifications: state.soundNotifications,
          showTimestamps: state.showTimestamps,
          compactMode: state.compactMode,
          temperature: state.temperature,
          maxTokens: state.maxTokens,
          defaultModel: state.defaultModel,
          notifications: state.notifications,
          chat: state.chat,
          advanced: state.advanced,
          // НЕ экспортируем API ключи из соображений безопасности
        };
        return JSON.stringify(exportData, null, 2);
      },

      importSettings: (json) => {
        try {
          const imported = JSON.parse(json);
          set({
            ...defaultSettings,
            ...imported,
            // НЕ импортируем API ключи
            apiKeys: get().apiKeys,
          });
          return true;
        } catch (error) {
          console.error("Failed to import settings:", error);
          return false;
        }
      },
    }),
    {
      name: "app-settings", // localStorage key
    }
  )
);
