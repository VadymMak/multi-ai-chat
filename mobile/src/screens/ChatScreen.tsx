import React from "react";
import { View, Text, StyleSheet } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";

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
  container: { flex: 1, backgroundColor: "#0A0A0A" },
  header: {
    padding: 16,
    borderBottomWidth: 1,
    borderBottomColor: "#222",
  },
  title: { color: "#FFFFFF", fontSize: 20, fontWeight: "bold" },
  body: { flex: 1, alignItems: "center", justifyContent: "center" },
  placeholder: { color: "#666666", fontSize: 16 },
});
