// File: src/services/apiClient.ts

import axios from "axios";
import { useModelStore } from "../store/modelStore";
import { useMemoryStore } from "../store/memoryStore";

// ✅ Use env var for baseURL
const baseURL = process.env.REACT_APP_BACKEND_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL,
  headers: {
    "Content-Type": "application/json",
  },
});

// ✅ Interceptor: Inject provider and role for all POSTs
apiClient.interceptors.request.use(
  (config) => {
    const provider = useModelStore.getState().provider;
    const role = useMemoryStore.getState().role;

    if (config.method === "post" && typeof config.data === "object") {
      config.data = {
        ...config.data,
        provider,
        role,
      };
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// ✅ Response interceptor: log errors
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("[API Error]", error.response || error.message);
    return Promise.reject(error);
  }
);

export default apiClient;
