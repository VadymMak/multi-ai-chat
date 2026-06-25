import axios from "axios";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { Config } from "./config";
import { STORAGE_KEYS } from "./constants";

export const api = axios.create({
  baseURL: Config.apiUrl,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 15000,
});

api.interceptors.request.use(async (config) => {
  const token = await AsyncStorage.getItem(STORAGE_KEYS.AUTH_TOKEN);
  if (token) {
    const clean = token.replace(/^"|"$/g, "").trim();
    if (clean) config.headers.Authorization = `Bearer ${clean}`;
  }
  return config;
});

// Injected by AuthProvider on mount; called when the server returns 401
let _onUnauthorized: (() => Promise<void>) | null = null;

export function setUnauthorizedHandler(handler: () => Promise<void>): void {
  _onUnauthorized = handler;
}

api.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if ((error as any)?.response?.status === 401 && _onUnauthorized) {
      await _onUnauthorized();
    }
    return Promise.reject(error);
  }
);
