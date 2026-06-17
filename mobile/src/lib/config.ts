export const Config = {
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? "https://multi-ai-chat-production.up.railway.app",
  appVersion: "1.0.0",
  isDev: __DEV__,
} as const;
