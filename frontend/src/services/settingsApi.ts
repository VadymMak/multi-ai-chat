// src/services/settingsApi.ts
import api from "./api";

// ==================== Types ====================

export interface APIKeysResponse {
  openai_key: string | null;
  anthropic_key: string | null;
  youtube_key: string | null;
  google_search_key: string | null;
  has_openai: boolean;
  has_anthropic: boolean;
  has_youtube: boolean;
  has_google_search: boolean;
}

export interface APIKeysUpdatePayload {
  openai_key?: string;
  anthropic_key?: string;
  youtube_key?: string;
  google_search_key?: string;
}

// ==================== API Functions ====================

/**
 * GET /settings/api-keys
 * Fetch user's API keys (masked for security)
 */
export const getAPIKeys = async (): Promise<APIKeysResponse> => {
  const response = await api.get<APIKeysResponse>("/settings/api-keys");
  return response.data;
};

/**
 * POST /settings/api-keys
 * Save user's API keys (encrypted on backend)
 * Only sends provided keys, doesn't delete existing ones unless explicitly set to empty string
 */
export const saveAPIKeys = async (
  keys: APIKeysUpdatePayload
): Promise<APIKeysResponse> => {
  const response = await api.post<APIKeysResponse>("/settings/api-keys", keys);
  return response.data;
};

/**
 * DELETE /settings/api-keys
 * Delete all user's API keys
 */
export const deleteAllAPIKeys = async (): Promise<{ message: string }> => {
  const response = await api.delete<{ message: string }>("/settings/api-keys");
  return response.data;
};

/**
 * Delete a specific API key by setting it to empty string
 */
export const deleteAPIKey = async (
  keyType: "openai" | "anthropic" | "youtube" | "google_search"
): Promise<APIKeysResponse> => {
  const payload: APIKeysUpdatePayload = {};

  switch (keyType) {
    case "openai":
      payload.openai_key = "";
      break;
    case "anthropic":
      payload.anthropic_key = "";
      break;
    case "youtube":
      payload.youtube_key = "";
      break;
    case "google_search":
      payload.google_search_key = "";
      break;
  }

  return saveAPIKeys(payload);
};

/**
 * Test a specific API key by saving it
 * Backend validates on save
 */
export const testAPIKey = async (
  keyType: "openai" | "anthropic" | "youtube" | "google_search",
  keyValue: string
): Promise<APIKeysResponse> => {
  const payload: APIKeysUpdatePayload = {};

  switch (keyType) {
    case "openai":
      payload.openai_key = keyValue;
      break;
    case "anthropic":
      payload.anthropic_key = keyValue;
      break;
    case "youtube":
      payload.youtube_key = keyValue;
      break;
    case "google_search":
      payload.google_search_key = keyValue;
      break;
  }

  return saveAPIKeys(payload);
};

// ==================== Helper Functions ====================

/**
 * Check if a key value is masked (already saved on server)
 */
export const isMaskedKey = (value: string): boolean => {
  return value.includes("...");
};

/**
 * Map UI key type names to API payload keys
 */
export const keyTypeToPayloadKey = (
  keyType: string
): keyof APIKeysUpdatePayload | null => {
  const map: Record<string, keyof APIKeysUpdatePayload> = {
    OpenAI: "openai_key",
    Anthropic: "anthropic_key",
    YouTube: "youtube_key",
    "Google Search": "google_search_key",
  };
  return map[keyType] || null;
};

/**
 * Map UI key type names to API key type
 */
export const keyTypeToApiType = (
  keyType: string
): "openai" | "anthropic" | "youtube" | "google_search" | null => {
  const map: Record<
    string,
    "openai" | "anthropic" | "youtube" | "google_search"
  > = {
    OpenAI: "openai",
    Anthropic: "anthropic",
    YouTube: "youtube",
    "Google Search": "google_search",
  };
  return map[keyType] || null;
};
