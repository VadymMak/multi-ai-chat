import axios from "axios";

const fallbackBaseURL =
  import.meta.env.MODE === "development"
    ? "http://localhost:8000/api"
    : "https://your-production-url.com/api"; // Replace with real prod URL

const baseURL = import.meta.env.VITE_API_BASE_URL || fallbackBaseURL;

if (!baseURL) {
  throw new Error("❌ API base URL is not defined. Check .env setup.");
}

console.log("[Axios] Base URL set to:", baseURL);

const axiosInstance = axios.create({
  baseURL,
  withCredentials: true,
  headers: {
    "Content-Type": "application/json",
  },
});

export default axiosInstance;
