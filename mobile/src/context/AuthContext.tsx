import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  ReactNode,
} from "react";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { get, set, remove } from "../lib/storage";
import { STORAGE_KEYS } from "../lib/constants";

const TOKEN_LIFETIME_MS = 86400_000 * 30;

export interface AuthUser {
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

async function clearAll() {
  await remove(STORAGE_KEYS.USER);
  await remove(STORAGE_KEYS.AUTH_TOKEN);
  await AsyncStorage.removeItem(STORAGE_KEYS.USER_ID);
  await AsyncStorage.removeItem(STORAGE_KEYS.TOKEN_EXPIRY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    async function restore() {
      try {
        const saved = await get<AuthUser>(STORAGE_KEYS.USER);
        if (!saved) return;

        const expiryStr = await AsyncStorage.getItem(STORAGE_KEYS.TOKEN_EXPIRY);
        if (expiryStr && new Date(expiryStr).getTime() < Date.now()) {
          await clearAll();
          return;
        }

        setUser(saved);
      } catch {
        // ignore restore errors — user stays logged out
      } finally {
        setIsLoading(false);
      }
    }
    restore();
  }, []);

  async function signIn(u: AuthUser, token: string, expiresAt?: string) {
    setUser(u);
    await set(STORAGE_KEYS.USER, u);
    await set(STORAGE_KEYS.AUTH_TOKEN, token);
    await AsyncStorage.setItem(STORAGE_KEYS.USER_ID, u.id);
    const expiry = expiresAt ?? new Date(Date.now() + TOKEN_LIFETIME_MS).toISOString();
    await AsyncStorage.setItem(STORAGE_KEYS.TOKEN_EXPIRY, expiry);
  }

  async function signOut() {
    setUser(null);
    await clearAll();
  }

  return (
    <AuthContext.Provider
      value={{ user, isLoading, isAuthenticated: user !== null, signIn, signOut }}
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
