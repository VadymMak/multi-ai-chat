import React, { useState } from "react";
import { Eye, EyeOff, Check, X, AlertCircle, ExternalLink } from "lucide-react";
import { toast } from "../../store/toastStore";

interface APIKeyStatus {
  isValid: boolean | null;
  message?: string;
}

export const APIKeysTab: React.FC = () => {
  // Form state
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [youtubeKey, setYoutubeKey] = useState("");
  const [googleSearchKey, setGoogleSearchKey] = useState("");
  const [googleSearchCx, setGoogleSearchCx] = useState("");

  // Show/hide state
  const [showOpenai, setShowOpenai] = useState(false);
  const [showAnthropic, setShowAnthropic] = useState(false);
  const [showYoutube, setShowYoutube] = useState(false);
  const [showGoogle, setShowGoogle] = useState(false);

  // Validation status (will be updated via backend later)
  const openaiStatus: APIKeyStatus = { isValid: null };
  const anthropicStatus: APIKeyStatus = { isValid: null };
  const youtubeStatus: APIKeyStatus = { isValid: null };
  const googleStatus: APIKeyStatus = { isValid: null };

  // Testing state
  const [testing, setTesting] = useState<string | null>(null);

  // Test button handler (UI only for now - backend TODO)
  const handleTest = async (keyType: string) => {
    setTesting(keyType);

    // Simulate API call delay
    await new Promise((resolve) => setTimeout(resolve, 1000));

    // TODO: Replace with actual backend call later
    toast.info(
      `Test functionality coming soon! This will validate your ${keyType} key.`
    );

    setTesting(null);
  };

  // Save handler (UI only for now - backend TODO)
  const handleSave = () => {
    // TODO: Replace with actual backend call later
    toast.success(
      "Save functionality coming soon! Your keys will be encrypted and stored securely."
    );
  };

  // Delete handler (UI only for now - backend TODO)
  const handleDelete = (keyType: string) => {
    if (!window.confirm(`Delete ${keyType} API key?`)) return;

    // TODO: Replace with actual backend call later
    toast.info(`Delete functionality coming soon!`);
  };

  const handleClear = () => {
    setOpenaiKey("");
    setAnthropicKey("");
    setYoutubeKey("");
    setGoogleSearchKey("");
    setGoogleSearchCx("");
    toast.info("Form cleared");
  };

  return (
    <div className="space-y-6">
      {/* Info Banner */}
      <div className="bg-blue-900/20 border border-blue-700 rounded-lg p-4">
        <div className="flex items-start gap-3">
          <AlertCircle className="text-blue-400 mt-1 flex-shrink-0" size={20} />
          <div>
            <h4 className="font-medium text-blue-300">
              Bring Your Own Keys (BYOK)
            </h4>
            <p className="text-sm text-gray-300 mt-1">
              Your API keys will be encrypted and stored securely. They are
              never shared with other users.
              <br />
              <span className="text-yellow-300">
                ⚠️ Backend storage coming soon - keys are temporary for now.
              </span>
            </p>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <h3 className="text-lg font-semibold text-gray-100">API Keys</h3>
        <p className="text-sm text-gray-400">
          Manage your AI provider API keys
        </p>

        {/* OpenAI API Key */}
        <KeyInputField
          label="OpenAI API Key"
          value={openaiKey}
          onChange={setOpenaiKey}
          show={showOpenai}
          onToggleShow={() => setShowOpenai(!showOpenai)}
          placeholder="sk-..."
          status={openaiStatus}
          onTest={() => void handleTest("OpenAI")}
          onDelete={() => handleDelete("OpenAI")}
          testing={testing === "OpenAI"}
          helpText="Get your key from OpenAI Platform"
          helpLink="https://platform.openai.com/api-keys"
        />

        {/* Anthropic API Key */}
        <KeyInputField
          label="Anthropic API Key"
          value={anthropicKey}
          onChange={setAnthropicKey}
          show={showAnthropic}
          onToggleShow={() => setShowAnthropic(!showAnthropic)}
          placeholder="sk-ant-..."
          status={anthropicStatus}
          onTest={() => void handleTest("Anthropic")}
          onDelete={() => handleDelete("Anthropic")}
          testing={testing === "Anthropic"}
          helpText="Get your key from Anthropic Console"
          helpLink="https://console.anthropic.com/settings/keys"
        />

        {/* YouTube API Key */}
        <KeyInputField
          label="YouTube Data API Key"
          value={youtubeKey}
          onChange={setYoutubeKey}
          show={showYoutube}
          onToggleShow={() => setShowYoutube(!showYoutube)}
          placeholder="AIza..."
          status={youtubeStatus}
          onTest={() => void handleTest("YouTube")}
          onDelete={() => handleDelete("YouTube")}
          testing={testing === "YouTube"}
          helpText="Get your key from Google Cloud Console"
          helpLink="https://console.developers.google.com/"
        />

        {/* Google Custom Search - NEW! */}
        <div className="p-4 bg-gray-800/50 border border-gray-700 rounded-lg space-y-4">
          <div>
            <h4 className="font-medium text-gray-200 mb-1">
              Google Custom Search (Optional)
            </h4>
            <p className="text-xs text-gray-400">
              Enable web search in debate mode. Free tier: 100 queries/day.
            </p>
          </div>

          <KeyInputField
            label="API Key"
            value={googleSearchKey}
            onChange={setGoogleSearchKey}
            show={showGoogle}
            onToggleShow={() => setShowGoogle(!showGoogle)}
            placeholder="AIza..."
            status={googleStatus}
            onTest={() => void handleTest("Google Search")}
            onDelete={() => handleDelete("Google Search")}
            testing={testing === "Google Search"}
            helpText="Get your key from Google Cloud Console"
            helpLink="https://console.developers.google.com/"
          />

          <div>
            <label className="block text-sm font-medium text-gray-300 mb-2">
              Custom Search Engine ID (CX)
            </label>
            <input
              type="text"
              value={googleSearchCx}
              onChange={(e) => setGoogleSearchCx(e.target.value)}
              placeholder="017576662..."
              className="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded text-white focus:outline-none focus:border-blue-500"
            />
            <div className="flex items-center gap-2 mt-1">
              <p className="text-xs text-gray-400">
                Create Custom Search Engine at Google Programmable Search
              </p>
              <a
                href="https://programmablesearchengine.google.com/"
                target="_blank"
                rel="noopener noreferrer"
                className="text-blue-400 hover:text-blue-300"
              >
                <ExternalLink size={14} />
              </a>
            </div>
          </div>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex justify-end gap-3 pt-4 border-t border-gray-700">
        <button
          onClick={handleClear}
          className="px-4 py-2 text-gray-300 hover:text-white transition-colors"
        >
          Clear
        </button>
        <button
          onClick={handleSave}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded transition-colors font-medium"
        >
          Save Changes
        </button>
      </div>
    </div>
  );
};

// ==================== Helper Component ====================

interface KeyInputFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  show: boolean;
  onToggleShow: () => void;
  placeholder: string;
  status: APIKeyStatus;
  onTest: () => void;
  onDelete: () => void;
  testing: boolean;
  helpText: string;
  helpLink: string;
}

const KeyInputField: React.FC<KeyInputFieldProps> = ({
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
}) => {
  const hasValue = value.length > 0;

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
                  <span className="ml-1 text-xs text-green-400">Valid</span>
                </>
              ) : (
                <>
                  <X size={16} className="text-red-500" />
                  <span className="ml-1 text-xs text-red-400">Invalid</span>
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
            className="w-full px-3 py-2 pr-10 bg-gray-700 border border-gray-600 rounded text-white focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={onToggleShow}
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-white transition-colors"
          >
            {show ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>

        {/* Test button */}
        <button
          onClick={onTest}
          disabled={!hasValue || testing}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white rounded transition-colors font-medium min-w-[80px]"
        >
          {testing ? "Testing..." : "Test"}
        </button>

        {/* Delete button (only show if has value) */}
        {hasValue && (
          <button
            onClick={onDelete}
            className="px-4 py-2 bg-red-600 hover:bg-red-700 text-white rounded transition-colors"
            title="Delete key"
          >
            Delete
          </button>
        )}
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

      {/* Status message */}
      {status.message && (
        <p
          className={`text-xs ${
            status.isValid ? "text-green-400" : "text-red-400"
          }`}
        >
          {status.message}
        </p>
      )}
    </div>
  );
};
