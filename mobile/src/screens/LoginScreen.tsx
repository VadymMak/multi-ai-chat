import React, { useState } from "react";
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import axios from "axios";
import { useAuthContext } from "../context/AuthContext";
import { Config } from "../lib/config";
import { colors, spacing, borderRadius } from "../theme";

export default function LoginScreen() {
  const { signIn } = useAuthContext();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleLogin = async () => {
    if (!username.trim() || !password) {
      setError("Введите логин и пароль");
      return;
    }

    setIsLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      params.append("username", username.trim());
      params.append("password", password);

      const { data: loginData } = await axios.post(
        `${Config.apiUrl}/api/auth/login`,
        params.toString(),
        { headers: { "Content-Type": "application/x-www-form-urlencoded" } }
      );

      const token: string = loginData.access_token;

      let user = {
        id: "unknown",
        email: "",
        name: username.trim(),
        role: "user",
      };

      try {
        const { data: me } = await axios.get(`${Config.apiUrl}/api/auth/me`, {
          headers: { Authorization: `Bearer ${token}` },
        });
        user = {
          id: String(me.id),
          email: me.email || "",
          name: me.username || me.name || username.trim(),
          role: me.is_superuser ? "admin" : "user",
        };
      } catch {
        // /me unavailable — use placeholder
      }

      await signIn(user, token);
    } catch (err: any) {
      const status = err.response?.status;
      if (status === 401 || status === 400) {
        setError("Неверный логин или пароль");
      } else if (status === 422) {
        setError("Введите логин и пароль");
      } else if (!err.response) {
        setError("Нет соединения с сервером");
      } else {
        setError("Ошибка входа. Попробуйте позже.");
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : "height"}
        style={styles.inner}
      >
        <View style={styles.logo}>
          <View style={styles.iconWrap}>
            <MaterialCommunityIcons name="brain" size={56} color={colors.accent} />
          </View>
          <Text style={styles.title}>Brain</Text>
          <Text style={styles.subtitle}>Персональный ИИ-ассистент</Text>
        </View>

        <View style={styles.form}>
          <TextInput
            style={styles.input}
            placeholder="Логин или email"
            placeholderTextColor={colors.textHint}
            value={username}
            onChangeText={(v) => { setUsername(v); setError(null); }}
            autoCapitalize="none"
            autoCorrect={false}
            returnKeyType="next"
          />
          <TextInput
            style={styles.input}
            placeholder="Пароль"
            placeholderTextColor={colors.textHint}
            value={password}
            onChangeText={(v) => { setPassword(v); setError(null); }}
            secureTextEntry
            returnKeyType="go"
            onSubmitEditing={handleLogin}
          />

          {error ? <Text style={styles.errorText}>{error}</Text> : null}

          <TouchableOpacity
            style={[styles.btn, isLoading && styles.btnDisabled]}
            onPress={handleLogin}
            disabled={isLoading}
            activeOpacity={0.8}
          >
            {isLoading ? (
              <ActivityIndicator color={colors.onAccent} />
            ) : (
              <Text style={styles.btnText}>Войти</Text>
            )}
          </TouchableOpacity>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  inner: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: spacing.md,
  },
  logo: { alignItems: "center", marginBottom: 48 },
  iconWrap: {
    width: 96,
    height: 96,
    borderRadius: borderRadius.xl,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderHi,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: spacing.md,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 36,
    fontWeight: "700",
    letterSpacing: 3,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 14,
    marginTop: 6,
  },
  form: { gap: 12 },
  input: {
    backgroundColor: colors.inputBg,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: borderRadius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: 14,
    color: colors.textPrimary,
    fontSize: 16,
  },
  errorText: {
    color: "#E05D5D",
    fontSize: 13,
    textAlign: "center",
  },
  btn: {
    backgroundColor: colors.accent,
    borderRadius: borderRadius.md,
    paddingVertical: 15,
    alignItems: "center",
    marginTop: 4,
  },
  btnDisabled: { opacity: 0.6 },
  btnText: {
    color: colors.onAccent,
    fontSize: 17,
    fontWeight: "700",
    letterSpacing: 0.5,
  },
});
