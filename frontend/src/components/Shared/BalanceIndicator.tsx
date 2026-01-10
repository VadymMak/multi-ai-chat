/**
 * Balance Indicator Component
 * Отображает баланс OpenAI и Claude API
 */
import React, { useEffect } from "react";
import {
  useBalanceStore,
  formatBalance,
  getBalanceColor,
  type BalanceInfo,
} from "../../store/balanceStore";
import { DollarSign, RefreshCw, AlertCircle } from "lucide-react";

interface BalanceIndicatorProps {
  /**
   * Показывать в компактном режиме (только иконки)
   */
  compact?: boolean;

  /**
   * Класс для кастомизации
   */
  className?: string;
}

/**
 * Определяет цвет иконки баланса
 */
function getBalanceIconColor(openai: BalanceInfo, claude: BalanceInfo): string {
  // Проверяем OpenAI (приоритет)
  if (openai.available && openai.balance && openai.balance !== "✅ Доступен") {
    const balance = parseFloat(
      openai.balance.replace("$", "").replace(",", "")
    );
    if (!isNaN(balance)) {
      if (balance < 5) return "text-error animate-pulse"; // Красный + пульсация
      if (balance < 10) return "text-error"; // Красный
      if (balance < 20) return "text-warning"; // Жёлтый
      return "text-success"; // Зелёный
    }
  }

  // Если OpenAI недоступен, проверяем Claude
  if (claude.available && claude.balance && claude.balance.startsWith("$")) {
    const balance = parseFloat(
      claude.balance.replace("$", "").replace(",", "")
    );
    if (!isNaN(balance)) {
      if (balance < 5) return "text-error animate-pulse";
      if (balance < 10) return "text-error";
      if (balance < 20) return "text-warning";
      return "text-success";
    }
  }

  // По умолчанию - серый
  return "text-text-secondary";
}

export default function BalanceIndicator({
  compact = false,
  className = "",
}: BalanceIndicatorProps) {
  const {
    openai,
    claude,
    isLoading,
    isCached,
    lastFetch,
    error,
    fetchBalance,
    clearCache,
  } = useBalanceStore();

  // Автообновление каждые 5 минут
  // Автообновление каждые 5 минут
  useEffect(() => {
    // Первичная загрузка
    fetchBalance();

    // Автообновление каждые 5 минут
    const interval = setInterval(() => {
      // Берём функцию напрямую из store на момент вызова
      useBalanceStore.getState().fetchBalance();
    }, 5 * 60 * 1000);

    // Cleanup
    return () => clearInterval(interval);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Намеренно пустой массив - fetchBalance стабилен

  const handleRefresh = async () => {
    await clearCache();
  };

  // Компактный режим (только иконка с tooltip)
  if (compact) {
    return (
      <div className={`relative group ${className}`}>
        <button
          onClick={() => fetchBalance(true)}
          disabled={isLoading}
          className="p-2 hover:bg-surface rounded-lg transition-colors relative"
          title="API Balance"
        >
          <DollarSign
            className={`w-5 h-5 ${
              isLoading ? "animate-spin" : ""
            } ${getBalanceIconColor(openai, claude)}`}
          />

          {/* Индикатор низкого баланса */}
          {openai.available &&
            openai.balance &&
            parseFloat(openai.balance.replace("$", "")) < 10 && (
              <span className="absolute top-1 right-1 w-2 h-2 bg-error rounded-full animate-pulse" />
            )}
        </button>

        {/* Tooltip при hover */}
        <div className="absolute right-0 top-full mt-2 w-64 p-3 bg-panel border border-border rounded-lg shadow-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50">
          <BalanceContent
            openai={openai}
            claude={claude}
            isLoading={isLoading}
            isCached={isCached}
            lastFetch={lastFetch}
            error={error}
            onRefresh={handleRefresh}
          />
        </div>
      </div>
    );
  }

  // Полный режим
  return (
    <div
      className={`bg-panel border border-border rounded-lg p-4 ${className}`}
    >
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-semibold text-text-primary flex items-center gap-2">
          <DollarSign className="w-4 h-4" />
          API Balance
        </h3>

        <button
          onClick={handleRefresh}
          disabled={isLoading}
          className="p-1 hover:bg-surface rounded transition-colors disabled:opacity-50"
          title="Обновить баланс"
        >
          <RefreshCw
            className={`w-4 h-4 text-text-secondary ${
              isLoading ? "animate-spin" : ""
            }`}
          />
        </button>
      </div>

      <BalanceContent
        openai={openai}
        claude={claude}
        isLoading={isLoading}
        isCached={isCached}
        lastFetch={lastFetch}
        error={error}
        onRefresh={handleRefresh}
      />
    </div>
  );
}

/**
 * Контент баланса (используется в обоих режимах)
 */
function BalanceContent({
  openai,
  claude,
  isLoading,
  isCached,
  lastFetch,
  error,
  onRefresh,
}: {
  openai: any;
  claude: any;
  isLoading: boolean;
  isCached: boolean;
  lastFetch: Date | null;
  error: string | null;
  onRefresh: () => void;
}) {
  if (isLoading && !openai.available && !claude.available) {
    return (
      <div className="flex items-center justify-center py-4">
        <RefreshCw className="w-5 h-5 animate-spin text-text-secondary" />
        <span className="ml-2 text-sm text-text-secondary">Загрузка...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center gap-2 text-error text-sm">
        <AlertCircle className="w-4 h-4" />
        <span>{error}</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* OpenAI Balance */}
      <BalanceItem provider="OpenAI" info={openai} icon="🤖" />

      {/* Claude Balance */}
      <BalanceItem provider="Claude" info={claude} icon="🧠" />

      {/* Meta info */}
      <div className="pt-2 border-t border-border">
        <div className="flex items-center justify-between text-xs text-text-secondary">
          <span>
            {isCached && "💾 Кеш"}
            {lastFetch && ` • ${formatLastFetch(lastFetch)}`}
          </span>
          <button
            onClick={onRefresh}
            className="hover:text-primary transition-colors"
          >
            Обновить
          </button>
        </div>
      </div>
    </div>
  );
}

/**
 * Элемент баланса для одного провайдера
 */
function BalanceItem({
  provider,
  info,
  icon,
}: {
  provider: string;
  info: any;
  icon: string;
}) {
  const balanceText = formatBalance(info);
  const colorClass = getBalanceColor(info);

  return (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-2">
        <span className="text-lg">{icon}</span>
        <div>
          <div className="text-sm font-medium text-text-primary">
            {provider}
          </div>
          {info.usage_this_month && info.usage_this_month !== "Неизвестно" && (
            <div className="text-xs text-text-secondary">
              Использовано: {info.usage_this_month}
            </div>
          )}
        </div>
      </div>

      <div className={`text-sm font-semibold ${colorClass}`}>{balanceText}</div>
    </div>
  );
}

/**
 * Форматирование времени последнего обновления
 */
function formatLastFetch(date: Date): string {
  const now = new Date();
  const diff = now.getTime() - date.getTime();
  const minutes = Math.floor(diff / 60000);

  if (minutes < 1) return "только что";
  if (minutes === 1) return "1 минуту назад";
  if (minutes < 5) return `${minutes} минуты назад`;
  return `${minutes} минут назад`;
}
