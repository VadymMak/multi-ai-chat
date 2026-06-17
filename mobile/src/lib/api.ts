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

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(error)
);
