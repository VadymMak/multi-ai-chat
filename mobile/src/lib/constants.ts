export const API_URL =
  process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000";

export const APP_VERSION = "1.0.0";

export const STORAGE_KEYS = {
  AUTH_TOKEN: "@multiaichat/auth_token",
  USER: "@multiaichat/user",
  USER_ID: "@multiaichat/user_id",
} as const;
