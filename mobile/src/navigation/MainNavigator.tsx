import React from "react";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { Ionicons } from "@expo/vector-icons";
import { colors } from "../theme";
import ChatScreen from "../screens/ChatScreen";
import NotesScreen from "../screens/NotesScreen";
import LessonsScreen from "../screens/LessonsScreen";
import RemindersScreen from "../screens/RemindersScreen";
import SettingsScreen from "../screens/SettingsScreen";

export type MainTabParamList = {
  Chat: undefined;
  Notes: undefined;
  Lessons: undefined;
  Reminders: undefined;
  Settings: undefined;
};

const Tab = createBottomTabNavigator<MainTabParamList>();

type IoniconsName = React.ComponentProps<typeof Ionicons>["name"];

export default function MainNavigator() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: colors.surface,
          borderTopColor: colors.border,
          borderTopWidth: 1,
          paddingBottom: 4,
        },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.textHint,
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
        tabBarIcon: ({ focused, color, size }) => {
          let iconName: IoniconsName;
          if (route.name === "Chat") {
            iconName = focused ? "chatbubble" : "chatbubble-outline";
          } else if (route.name === "Notes") {
            iconName = focused ? "bookmark" : "bookmark-outline";
          } else if (route.name === "Lessons") {
            iconName = focused ? "book" : "book-outline";
          } else if (route.name === "Reminders") {
            iconName = focused ? "alarm" : "alarm-outline";
          } else {
            iconName = focused ? "settings" : "settings-outline";
          }
          return <Ionicons name={iconName} size={size} color={color} />;
        },
      })}
    >
      <Tab.Screen name="Chat" component={ChatScreen} options={{ tabBarLabel: "Чат" }} />
      <Tab.Screen name="Notes" component={NotesScreen} options={{ tabBarLabel: "Заметки" }} />
      <Tab.Screen name="Lessons" component={LessonsScreen} options={{ tabBarLabel: "Уроки" }} />
      <Tab.Screen name="Reminders" component={RemindersScreen} options={{ tabBarLabel: "Будильник" }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ tabBarLabel: "Настройки" }} />
    </Tab.Navigator>
  );
}
