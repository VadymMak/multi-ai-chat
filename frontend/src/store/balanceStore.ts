/**
 * Balance Store
 * Управление состоянием балансов API (OpenAI и Claude)
 */
import { create } from "zustand";
import api from "../services/api";
import { toast } from "./toastStore";

export interface BalanceInfo {
  available: boolean;
  balance: string | null;
  usage_this_month: string | null;
  error: string | null;
  last_updated: string | null;
}

export interface BalanceState {
  openai: BalanceInfo;
  claude: BalanceInfo;
  isLoading: boolean;
  isCached: boolean;
  lastFetch: Date | null;
  error: string | null;
}

interface BalanceStore extends BalanceState {
  // Actions
  fetchBalance: (forceRefresh?: boolean) => Promise<void>;
  clearCache: () => Promise<void>;
  reset: () => void;
}

const initialBalanceInfo: BalanceInfo = {
  available: false,
  balance: null,
  usage_this_month: null,
  error: null,
  last_updated: null,
};

const initialState: BalanceState = {
  openai: initialBalanceInfo,
  claude: initialBalanceInfo,
  isLoading: false,
  isCached: false,
  lastFetch: null,
  error: null,
};

export const useBalanceStore = create<BalanceStore>((set, get) => ({
  ...initialState,

  /**
   * Получить балансы API
   * @param forceRefresh - Принудительно обновить (игнорировать кеш)
   */
  fetchBalance: async (forceRefresh = false) => {
    console.log("🔍 [BalanceStore] Fetching balance...", { forceRefresh });
    set({ isLoading: true, error: null });

    try {
      const params = forceRefresh ? { force_refresh: true } : {};
      console.log("🔍 [BalanceStore] Calling /balance with params:", params);

      const response = await api.get("/balance", { params });
      console.log("✅ [BalanceStore] Response data:", response.data);

      // ✅ DEMO MODE: Подменяем баланс для демонстрации
      let openaiData = response.data.openai;
      let claudeData = response.data.claude;

      if (DEMO_LOW_BALANCE) {
        console.log(
          `🎭 [DEMO MODE] Overriding OpenAI balance to $${DEMO_BALANCE_VALUE}`
        );
        openaiData = {
          available: true,
          balance: `$${DEMO_BALANCE_VALUE.toFixed(2)}`,
          usage_this_month: "$2.35",
          error: null,
          last_updated: new Date().toISOString(),
        };
      }

      set({
        openai: openaiData,
        claude: claudeData,
        isCached: response.data.cached,
        lastFetch: new Date(),
        isLoading: false,
        error: null,
      });

      console.log("✅ [BalanceStore] Balance updated successfully");
      checkLowBalance(openaiData, claudeData);
    } catch (error) {
      console.error("❌ [BalanceStore] Failed to fetch balance:", error);
      set({
        error: error instanceof Error ? error.message : "Unknown error",
        isLoading: false,
      });
    }
  },

  /**
   * Очистить кеш на backend
   */
  clearCache: async () => {
    try {
      await api.post("/balance/clear-cache");

      // После очистки кеша, получаем свежие данные
      await get().fetchBalance(true);
    } catch (error) {
      console.error("Failed to clear cache:", error);
    }
  },

  /**
   * Сбросить состояние
   */
  reset: () => {
    set(initialState);
  },
}));

/**
 * Проверка низкого баланса и показ предупреждений
 */
const lowBalanceWarningsShown = {
  openai: false,
  claude: false,
};

// ✅ DEMO MODE для тестирования уведомлений
const DEMO_LOW_BALANCE = false; // ← Включи true для теста уведомлений
const DEMO_BALANCE_VALUE = 15; // ← Значение для демо

function checkLowBalance(openai: BalanceInfo, claude: BalanceInfo) {
  const LOW_BALANCE_THRESHOLD = 10; // $10
  const CRITICAL_BALANCE_THRESHOLD = 5; // $5

  // ✅ DEMO MODE: Показываем уведомление с фейковым балансом
  if (DEMO_LOW_BALANCE && !lowBalanceWarningsShown.openai) {
    console.log("🎭 [DEMO MODE] Simulating low balance warning");

    if (DEMO_BALANCE_VALUE < CRITICAL_BALANCE_THRESHOLD) {
      toast.error(
        `⚠️ OpenAI balance critically low: $${DEMO_BALANCE_VALUE.toFixed(
          2
        )}. Please add funds!`,
        5000
      );
    } else if (DEMO_BALANCE_VALUE < LOW_BALANCE_THRESHOLD) {
      toast.warning(
        `⚠️ OpenAI balance is low: $${DEMO_BALANCE_VALUE.toFixed(2)}`,
        5000
      );
    }
    lowBalanceWarningsShown.openai = true;
    return;
  }

  // ✅ РЕАЛЬНАЯ ПРОВЕРКА OpenAI
  if (openai.available && openai.balance && openai.balance !== "✅ Доступен") {
    const balanceStr = openai.balance.replace("$", "").replace(",", "");
    const balance = parseFloat(balanceStr);

    if (!isNaN(balance)) {
      console.log(`💰 [OpenAI] Balance check: $${balance.toFixed(2)}`);

      if (
        balance < CRITICAL_BALANCE_THRESHOLD &&
        !lowBalanceWarningsShown.openai
      ) {
        toast.error(
          `⚠️ OpenAI balance critically low: $${balance.toFixed(
            2
          )}. Please add funds!`,
          5000
        );
        lowBalanceWarningsShown.openai = true;
      } else if (
        balance < LOW_BALANCE_THRESHOLD &&
        !lowBalanceWarningsShown.openai
      ) {
        toast.warning(`⚠️ OpenAI balance is low: $${balance.toFixed(2)}`, 5000);
        lowBalanceWarningsShown.openai = true;
      }
    }
  }

  // ✅ РЕАЛЬНАЯ ПРОВЕРКА Claude
  if (claude.available && claude.balance && claude.balance.startsWith("$")) {
    const balanceStr = claude.balance.replace("$", "").replace(",", "");
    const balance = parseFloat(balanceStr);

    if (!isNaN(balance)) {
      console.log(`💰 [Claude] Balance check: $${balance.toFixed(2)}`);

      if (
        balance < CRITICAL_BALANCE_THRESHOLD &&
        !lowBalanceWarningsShown.claude
      ) {
        toast.error(
          `⚠️ Claude balance critically low: $${balance.toFixed(
            2
          )}. Please add credits!`,
          5000
        );
        lowBalanceWarningsShown.claude = true;
      } else if (
        balance < LOW_BALANCE_THRESHOLD &&
        !lowBalanceWarningsShown.claude
      ) {
        toast.warning(`⚠️ Claude balance is low: $${balance.toFixed(2)}`, 5000);
        lowBalanceWarningsShown.claude = true;
      }
    }
  }
}

/**
 * Утилита для форматирования баланса
 */
export function formatBalance(info: BalanceInfo): string {
  // Если недоступно, показываем ошибку
  if (!info.available) {
    return info.error || "Недоступно";
  }

  // Claude возвращает "Доступен"
  if (info.balance === "Доступен") {
    return "✅ Доступен";
  }

  // OpenAI возвращает "$X.XX"
  if (info.balance) {
    return info.balance;
  }

  return "Неизвестно";
}

/**
 * Утилита для получения цвета статуса
 */
export function getBalanceColor(info: BalanceInfo): string {
  if (!info.available) {
    return "text-error"; // красный
  }

  if (info.balance && info.balance !== "Доступен") {
    const balance = parseFloat(info.balance.replace("$", ""));
    if (balance < 5) return "text-error"; // красный
    if (balance < 20) return "text-warning"; // оранжевый
    return "text-success"; // зеленый
  }

  return "text-success"; // зеленый для "Доступен"
}
