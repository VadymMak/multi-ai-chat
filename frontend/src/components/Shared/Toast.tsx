import React, { useEffect, useState } from "react";
import { CheckCircle, AlertCircle, Info, X, AlertTriangle } from "lucide-react"; // ← Добавили AlertTriangle
import type { ToastType } from "../../store/toastStore";

interface ToastProps {
  message: string;
  type?: ToastType;
  duration?: number;
  onClose: () => void;
}

const Toast: React.FC<ToastProps> = ({
  message,
  type = "info",
  duration = 3000,
  onClose,
}) => {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false);
      setTimeout(onClose, 300); // Wait for fade out
    }, duration);

    return () => clearTimeout(timer);
  }, [duration, onClose]);

  const icons = {
    success: <CheckCircle size={20} className="text-success" />,
    error: <AlertCircle size={20} className="text-error" />,
    info: <Info size={20} className="text-primary" />,
    warning: <AlertTriangle size={20} className="text-warning" />, // ← Добавили warning
  };

  const bgColors = {
    success: "bg-success/10 border-success/30",
    error: "bg-error/10 border-error/30",
    info: "bg-primary/10 border-primary/30",
    warning: "bg-warning/10 border-warning/30", // ← Добавили warning
  };

  const handleClose = () => {
    setIsVisible(false);
    setTimeout(onClose, 300);
  };

  return (
    <div
      className={`
        flex items-center gap-3
        px-4 py-3 rounded-lg border
        shadow-lg backdrop-blur-sm
        ${bgColors[type]}
        transition-all duration-300
        ${isVisible ? "opacity-100 translate-y-0" : "opacity-0 -translate-y-2"}
      `}
    >
      {icons[type]}
      <p className="text-sm font-medium text-text-primary">{message}</p>
      <button
        onClick={handleClose}
        className="ml-2 p-1 rounded hover:bg-surface transition"
        type="button"
      >
        <X size={16} className="text-text-secondary" />
      </button>
    </div>
  );
};

export default Toast;
