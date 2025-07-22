// src/services/api.ts
import axios from "axios";

// ✅ CRA requires REACT_APP_ prefix
const baseURL = process.env.REACT_APP_API_BASE_URL;

if (!baseURL) {
  console.warn(
    "⚠️ REACT_APP_API_BASE_URL is not defined. Falling back to localhost."
  );
}

console.debug("🌍 Axios baseURL:", baseURL);

const api = axios.create({
  baseURL: baseURL || "http://localhost:8000/api", // fallback safety
  timeout: 300000,
  withCredentials: false,
});

export default api;
