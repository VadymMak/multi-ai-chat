export const Config = {
  apiUrl: process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000",
  appVersion: "1.0.0",
  isDev: __DEV__,
} as const;
