// src/components/Settings/APIKeysTab.tsx
import React, { useState, useEffect, useCallback } from "react";
import { AlertCircle, ExternalLink, Loader2 } from "lucide-react";
import { toast } from "../../store/toastStore";
import {
  getAPIKeys,
  saveAPIKeys,
  testAPIKey,
  deleteAPIKey,
  isMaskedKey,
  keyTypeToApiType,
  type APIKeysResponse,
} from "../../services/settingsApi";
import { APIKeyInput, type APIKeyStatus } from "./APIKeyInput";

export const APIKeysTab: React.FC = () => {
  // Form state
  const [openaiKey, setOpenaiKey] = useState("");
  const [anthropicKey, setAnthropicKey] = useState("");
  const [youtubeKey, setYoutubeKey] = useState("");
  const [googleSearchKey, setGoogleSearchKey] = useState("");
  const [googleSearchCx, setGoogleSearchCx] = useState("");

  // Track which keys exist on server
  const [existingKeys, setExistingKeys] = useState<APIKeysResponse | null>(
    null
  );

  // Show/hide state
  const [showOpenai, setShowOpenai] = useState(false);
  const [showAnthropic, setShowAnthropic] = useState(false);
  const [showYoutube, setShowYoutube] = useState(false);
  const [showGoogle, setShowGoogle] = useState(false);

  // Validation status
  const [openaiStatus, setOpenaiStatus] = useState<APIKeyStatus>({
    isValid: null,
  });
  const [anthropicStatus, setAnthropicStatus] = useState<APIKeyStatus>({
    isValid: null,
  });
  const [youtubeStatus, setYoutubeStatus] = useState<APIKeyStatus>({
    isValid: null,
  });
  const [googleStatus, setGoogleStatus] = useState<APIKeyStatus>({
    isValid: null,
  });

  // Loading states
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);

  // ==================== Load existing keys on mount ====================
  useEffect(() => {
    const loadKeys = async () => {
      try {
        const data = await getAPIKeys();
        setExistingKeys(data);

        // Set masked values as placeholders
        if (data.openai_key) setOpenaiKey(data.openai_key);
        if (data.anthropic_key) setAnthropicKey(data.anthropic_key);
        if (data.youtube_key) setYoutubeKey(data.youtube_key);
        if (data.google_search_key) setGoogleSearchKey(data.google_search_key);

        // Update status based on existing keys
        if (data.has_openai)
          setOpenaiStatus({ isValid: true, message: "Saved" });
        if (data.has_anthropic)
          setAnthropicStatus({ isValid: true, message: "Saved" });
        if (data.has_youtube)
          setYoutubeStatus({ isValid: true, message: "Saved" });
        if (data.has_google_search)
          setGoogleStatus({ isValid: true, message: "Saved" });
      } catch (error) {
        console.error("Failed to load API keys:", error);
        toast.error("Failed to load API keys");
      } finally {
        setLoading(false);
      }
    };

    loadKeys();
  }, []);

  // ==================== Get key value by type ====================
  const getKeyValue = useCallback(
    (keyType: string): string => {
      switch (keyType) {
        case "OpenAI":
          return openaiKey;
        case "Anthropic":
          return anthropicKey;
        case "YouTube":
          return youtubeKey;
        case "Google Search":
          return googleSearchKey;
        default:
          return "";
      }
    },
    [openaiKey, anthropicKey, youtubeKey, googleSearchKey]
  );

  // ==================== Update status and value after API response ====================
  const updateAfterResponse = useCallback((data: APIKeysResponse) => {
    setExistingKeys(data);

    if (data.openai_key) {
      setOpenaiKey(data.openai_key);
      setOpenaiStatus({ isValid: true, message: "Saved" });
    }
    if (data.anthropic_key) {
      setAnthropicKey(data.anthropic_key);
      setAnthropicStatus({ isValid: true, message: "Saved" });
    }
    if (data.youtube_key) {
      setYoutubeKey(data.youtube_key);
      setYoutubeStatus({ isValid: true, message: "Saved" });
    }
    if (data.google_search_key) {
      setGoogleSearchKey(data.google_search_key);
      setGoogleStatus({ isValid: true, message: "Saved" });
    }
  }, []);

  // ==================== Test API Key ====================
  const handleTest = useCallback(
    async (keyType: string) => {
      const key = getKeyValue(keyType);

      if (!key || key.trim() === "") {
        toast.error(`Please enter a ${keyType} API key first`);
        return;
      }

      if (isMaskedKey(key)) {
        toast.info(`${keyType} key is already saved`);
        return;
      }

      const apiType = keyTypeToApiType(keyType);
      if (!apiType) {
        toast.error(`Unknown key type: ${keyType}`);
        return;
      }

      setTesting(keyType);

      try {
        const data = await testAPIKey(apiType, key);
        updateAfterResponse(data);
        toast.success(`${keyType} API key saved successfully!`);
      } catch (error: any) {
        const message = error?.detail || `Failed to validate ${keyType} key`;
        toast.error(message);

        // Update status to invalid
        switch (keyType) {
          case "OpenAI":
            setOpenaiStatus({ isValid: false, message: "Invalid" });
            break;
          case "Anthropic":
            setAnthropicStatus({ isValid: false, message: "Invalid" });
            break;
          case "YouTube":
            setYoutubeStatus({ isValid: false, message: "Invalid" });
            break;
          case "Google Search":
            setGoogleStatus({ isValid: false, message: "Invalid" });
            break;
        }
      } finally {
        setTesting(null);
      }
    },
    [getKeyValue, updateAfterResponse]
  );

  // ==================== Save All Keys ====================
  const handleSave = useCallback(async () => {
    setSaving(true);

    try {
      // Only send keys that are not masked (new or changed)
      const payload: Record<string, string> = {};

      if (openaiKey && !isMaskedKey(openaiKey)) {
        payload.openai_key = openaiKey;
      }
      if (anthropicKey && !isMaskedKey(anthropicKey)) {
        payload.anthropic_key = anthropicKey;
      }
      if (youtubeKey && !isMaskedKey(youtubeKey)) {
        payload.youtube_key = youtubeKey;
      }
      if (googleSearchKey && !isMaskedKey(googleSearchKey)) {
        payload.google_search_key = googleSearchKey;
      }

      if (Object.keys(payload).length === 0) {
        toast.info("No new keys to save");
        setSaving(false);
        return;
      }

      const data = await saveAPIKeys(payload);
      updateAfterResponse(data);
      toast.success("API keys saved successfully!");
    } catch (error: any) {
      const message = error?.detail || "Failed to save API keys";
      toast.error(message);
    } finally {
      setSaving(false);
    }
  }, [
    openaiKey,
    anthropicKey,
    youtubeKey,
    googleSearchKey,
    updateAfterResponse,
  ]);

  // ==================== Delete Key ====================
  const handleDelete = useCallback(async (keyType: string) => {
    if (!window.confirm(`Delete ${keyType} API key?`)) return;

    const apiType = keyTypeToApiType(keyType);
    if (!apiType) {
      toast.error(`Unknown key type: ${keyType}`);
      return;
    }

    try {
      const data = await deleteAPIKey(apiType);
      setExistingKeys(data);

      // Clear the deleted key
      switch (keyType) {
        case "OpenAI":
          setOpenaiKey("");
          setOpenaiStatus({ isValid: null });
          break;
        case "Anthropic":
          setAnthropicKey("");
          setAnthropicStatus({ isValid: null });
          break;
        case "YouTube":
          setYoutubeKey("");
          setYoutubeStatus({ isValid: null });
          break;
        case "Google Search":
          setGoogleSearchKey("");
          setGoogleStatus({ isValid: null });
          break;
      }

      toast.success(`${keyType} API key deleted`);
    } catch (error: any) {
      const message = error?.detail || `Failed to delete ${keyType} key`;
      toast.error(message);
    }
  }, []);

  // ==================== Cancel / Reset Form ====================
  const handleCancel = useCallback(() => {
    if (existingKeys) {
      setOpenaiKey(existingKeys.openai_key || "");
      setAnthropicKey(existingKeys.anthropic_key || "");
      setYoutubeKey(existingKeys.youtube_key || "");
      setGoogleSearchKey(existingKeys.google_search_key || "");
    } else {
      setOpenaiKey("");
      setAnthropicKey("");
      setYoutubeKey("");
      setGoogleSearchKey("");
    }
    setGoogleSearchCx("");
    toast.info("Changes discarded");
  }, [existingKeys]);

  // ==================== Loading State ====================
  if (loading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="animate-spin text-blue-500" size={32} />
        <span className="ml-3 text-gray-400">Loading API keys...</span>
      </div>
    );
  }

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
              Your API keys are encrypted with AES-256 and stored securely. They
              are never shared with other users.
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
        <APIKeyInput
          label="OpenAI API Key"
          value={openaiKey}
          onChange={setOpenaiKey}
          show={showOpenai}
          onToggleShow={() => setShowOpenai(!showOpenai)}
          placeholder="sk-..."
          status={openaiStatus}
          onTest={() => handleTest("OpenAI")}
          onDelete={() => handleDelete("OpenAI")}
          testing={testing === "OpenAI"}
          helpText="Get your key from OpenAI Platform"
          helpLink="https://platform.openai.com/api-keys"
          hasExisting={existingKeys?.has_openai || false}
        />

        {/* Anthropic API Key */}
        <APIKeyInput
          label="Anthropic API Key"
          value={anthropicKey}
          onChange={setAnthropicKey}
          show={showAnthropic}
          onToggleShow={() => setShowAnthropic(!showAnthropic)}
          placeholder="sk-ant-..."
          status={anthropicStatus}
          onTest={() => handleTest("Anthropic")}
          onDelete={() => handleDelete("Anthropic")}
          testing={testing === "Anthropic"}
          helpText="Get your key from Anthropic Console"
          helpLink="https://console.anthropic.com/settings/keys"
          hasExisting={existingKeys?.has_anthropic || false}
        />

        {/* YouTube API Key */}
        <APIKeyInput
          label="YouTube Data API Key"
          value={youtubeKey}
          onChange={setYoutubeKey}
          show={showYoutube}
          onToggleShow={() => setShowYoutube(!showYoutube)}
          placeholder="AIza..."
          status={youtubeStatus}
          onTest={() => handleTest("YouTube")}
          onDelete={() => handleDelete("YouTube")}
          testing={testing === "YouTube"}
          helpText="Get your key from Google Cloud Console"
          helpLink="https://console.developers.google.com/"
          hasExisting={existingKeys?.has_youtube || false}
        />

        {/* Google Custom Search */}
        <div className="p-4 bg-gray-800/50 border border-gray-700 rounded-lg space-y-4">
          <div>
            <h4 className="font-medium text-gray-200 mb-1">
              Google Custom Search (Optional)
            </h4>
            <p className="text-xs text-gray-400">
              Enable web search in debate mode. Free tier: 100 queries/day.
            </p>
          </div>

          <APIKeyInput
            label="API Key"
            value={googleSearchKey}
            onChange={setGoogleSearchKey}
            show={showGoogle}
            onToggleShow={() => setShowGoogle(!showGoogle)}
            placeholder="AIza..."
            status={googleStatus}
            onTest={() => handleTest("Google Search")}
            onDelete={() => handleDelete("Google Search")}
            testing={testing === "Google Search"}
            helpText="Get your key from Google Cloud Console"
            helpLink="https://console.developers.google.com/"
            hasExisting={existingKeys?.has_google_search || false}
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

      {/* Action Buttons */}
      <div className="flex justify-end gap-3 pt-4 border-t border-gray-700">
        <button
          onClick={handleCancel}
          className="px-4 py-2 text-gray-300 hover:text-white transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800 disabled:cursor-wait text-white rounded transition-colors font-medium flex items-center gap-2"
        >
          {saving && <Loader2 className="animate-spin" size={16} />}
          {saving ? "Saving..." : "Save Changes"}
        </button>
      </div>
    </div>
  );
};

export default APIKeysTab;
