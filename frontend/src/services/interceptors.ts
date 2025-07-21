// File: src/services/interceptors.ts

import apiClient from "./apiClient";
import { useModelStore } from "../store/modelStore";
import { useMemoryStore } from "../store/memoryStore";

// Access state outside of React (Zustand provides this safely)
const getModel = () => useModelStore.getState().provider;
const getRole = () => useMemoryStore.getState().role;

apiClient.interceptors.request.use(
  (config) => {
    const provider = getModel();
    const role = getRole();

    // If it's a POST request with a body, inject provider + role
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

// Optional: global error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error("[API Error]", error.response || error.message);
    return Promise.reject(error);
  }
);
