export const API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? "https://multi-ai-chat-production.up.railway.app";

export const APP_VERSION = "1.0.0";

export const STORAGE_KEYS = {
  AUTH_TOKEN: "@multiaichat/auth_token",
  USER: "@multiaichat/user",
  USER_ID: "@multiaichat/user_id",
  TOKEN_EXPIRY: "@multiaichat/token_expiry",
  DEFAULT_MODEL: "@multiaichat/default_model",
  REMINDERS: "@multiaichat/reminders",
} as const;
