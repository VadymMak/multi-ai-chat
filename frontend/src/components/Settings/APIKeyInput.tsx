// src/components/Settings/APIKeyInput.tsx
import React from "react";
import { Eye, EyeOff, Check, X, ExternalLink, Loader2 } from "lucide-react";

export interface APIKeyStatus {
  isValid: boolean | null;
  message?: string;
}

interface APIKeyInputProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  show: boolean;
  onToggleShow: () => void;
  placeholder: string;
  status: APIKeyStatus;
  onTest: () => void;
  onDelete?: () => void;
  testing: boolean;
  helpText: string;
  helpLink: string;
  hasExisting: boolean;
  disabled?: boolean;
}

export const APIKeyInput: React.FC<APIKeyInputProps> = ({
  label,
  value,
  onChange,
  show,
  onToggleShow,
  placeholder,
  status,
  onTest,
  onDelete,
  testing,
  helpText,
  helpLink,
  hasExisting,
  disabled = false,
}) => {
  const hasValue = value.length > 0;
  const isMasked = value.includes("...");

  return (
    <div className="space-y-2">
      {/* Label with status indicator */}
      <div className="flex items-center justify-between">
        <label className="block text-sm font-medium text-gray-300">
          {label}
          {status.isValid !== null && (
            <span className="ml-2 inline-flex items-center">
              {status.isValid ? (
                <>
                  <Check size={16} className="text-green-500" />
                  <span className="ml-1 text-xs text-green-400">
                    {status.message || "Valid"}
                  </span>
                </>
              ) : (
                <>
                  <X size={16} className="text-red-500" />
                  <span className="ml-1 text-xs text-red-400">
                    {status.message || "Invalid"}
                  </span>
                </>
              )}
            </span>
          )}
        </label>
      </div>

      {/* Input with show/hide and action buttons */}
      <div className="flex gap-2">
        <div className="flex-1 relative">
          <input
            type={show ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            disabled={disabled}
            className={`w-full px-3 py-2 pr-10 bg-gray-700 border rounded text-white focus:outline-none focus:border-blue-500 disabled:opacity-50 disabled:cursor-not-allowed ${
              hasExisting ? "border-green-600" : "border-gray-600"
            }`}
          />
          <button
            onClick={onToggleShow}
            type="button"
            disabled={disabled}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors disabled:opacity-50"
          >
            {show ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>

        {/* Test button */}
        <button
          onClick={onTest}
          disabled={!hasValue || testing || disabled}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded transition-colors font-medium min-w-[80px] flex items-center justify-center gap-2"
        >
          {testing ? (
            <>
              <Loader2 className="animate-spin" size={16} />
              <span>...</span>
            </>
          ) : (
            "Test"
          )}
        </button>
      </div>

      {/* Help text with link */}
      <div className="flex items-center gap-2">
        <p className="text-xs text-gray-400">{helpText}</p>
        <a
          href={helpLink}
          target="_blank"
          rel="noopener noreferrer"
          className="text-blue-400 hover:text-blue-300 transition-colors"
        >
          <ExternalLink size={14} />
        </a>
      </div>

      {/* Hint for masked keys */}
      {isMasked && (
        <p className="text-xs text-gray-500 italic">
          Key is saved. Enter a new key to replace it.
        </p>
      )}
    </div>
  );
};

export default APIKeyInput;
