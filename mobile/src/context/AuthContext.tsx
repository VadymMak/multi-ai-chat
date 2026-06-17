import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import axios from "axios";
import { get, set, remove } from "../lib/storage";
import { STORAGE_KEYS, API_URL } from "../lib/constants";

const TOKEN_LIFETIME_MS = 86400_000 * 30; // 30 days
const REFRESH_THRESHOLD_DAYS = 7; // refresh if < 7 days left

interface AuthUser {
  id: string;
  email: string;
  name: string | null;
  role: string;
}

interface AuthContextValue {
  user: AuthUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  signIn: (user: AuthUser, token: string, expiresAt?: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function restore() {
      const saved = await get<AuthUser>(STORAGE_KEYS.USER);
      if (!saved) {
        setIsLoading(false);
        return;
      }

      const expiryStr = await AsyncStorage.getItem(STORAGE_KEYS.TOKEN_EXPIRY);
      if (expiryStr) {
        const expiryDate = new Date(expiryStr);
        const daysLeft = (expiryDate.getTime() - Date.now()) / (1000 * 60 * 60 * 24);

        if (daysLeft < 0) {
          // Token fully expired — force logout
          await AsyncStorage.multiRemove([
            STORAGE_KEYS.USER,
            STORAGE_KEYS.AUTH_TOKEN,
            STORAGE_KEYS.USER_ID,
            STORAGE_KEYS.TOKEN_EXPIRY,
          ]);
          setIsLoading(false);
          return;
        }

        if (daysLeft < REFRESH_THRESHOLD_DAYS) {
          // Token expiring soon — silent refresh
          try {
            const userId = await AsyncStorage.getItem(STORAGE_KEYS.USER_ID);
            const res = await axios.post(
              `${API_URL}/api/auth/refresh`,
              {},
              { headers: { Authorization: `Bearer ${userId}` } }
            );
            if (res.data?.expiresAt) {
              await AsyncStorage.setItem(STORAGE_KEYS.TOKEN_EXPIRY, res.data.expiresAt);
            }
          } catch {
            // Silent fail — user stays logged in, try again next launch
          }
        }
      } else {
        // No expiry stored (user logged in before this feature) — set it now
        await AsyncStorage.setItem(
          STORAGE_KEYS.TOKEN_EXPIRY,
          new Date(Date.now() + TOKEN_LIFETIME_MS).toISOString()
        );
      }

      setUser(saved);
      setIsLoading(false);
    }
    restore();
  }, []);

  async function signIn(user: AuthUser, token: string, expiresAt?: string) {
    // Set user first so isAuthenticated flips immediately and
    // AppNavigator can react before AsyncStorage writes complete
    setUser(user);
    await set(STORAGE_KEYS.USER, user);
    await set(STORAGE_KEYS.AUTH_TOKEN, token);
    // Store userId as plain string (NOT JSON.stringify) so api.ts
    // interceptor reads a clean value without quotes
    await AsyncStorage.setItem(STORAGE_KEYS.USER_ID, user.id);
    const expiry = expiresAt ?? new Date(Date.now() + TOKEN_LIFETIME_MS).toISOString();
    await AsyncStorage.setItem(STORAGE_KEYS.TOKEN_EXPIRY, expiry);
  }

  async function signOut() {
    await remove(STORAGE_KEYS.USER);
    await remove(STORAGE_KEYS.AUTH_TOKEN);
    await AsyncStorage.removeItem(STORAGE_KEYS.USER_ID);
    await AsyncStorage.removeItem(STORAGE_KEYS.TOKEN_EXPIRY);
    // STORAGE_KEYS.ONBOARDING_COMPLETE is intentionally kept
    setUser(null);
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: user !== null,
        signIn,
        signOut,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuthContext(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuthContext must be used within AuthProvider");
  return ctx;
}
