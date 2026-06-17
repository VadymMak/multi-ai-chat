import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { colors } from "../theme";

export default function ChatScreen() {
  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Multi-AI Chat</Text>
      </View>
      <View style={styles.body}>
        <Text style={styles.placeholder}>Chat placeholder — Brain features coming soon</Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: colors.bg },
  header: {
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  title: { color: colors.textPrimary, fontSize: 20, fontWeight: "bold" },
  body: { flex: 1, alignItems: "center", justifyContent: "center" },
  placeholder: { color: colors.textHint, fontSize: 16 },
});
