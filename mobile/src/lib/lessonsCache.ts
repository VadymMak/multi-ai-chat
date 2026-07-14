import AsyncStorage from "@react-native-async-storage/async-storage";
import { Lesson } from "./lessonApi";

const KEYS = {
  list: "@lessons/list",
  body: (id: number) => `@lessons/body/${id}`,
} as const;

export const lessonsCache = {
  saveList: (lessons: Lesson[]) =>
    AsyncStorage.setItem(KEYS.list, JSON.stringify(lessons)),

  loadList: async (): Promise<Lesson[]> => {
    try {
      const raw = await AsyncStorage.getItem(KEYS.list);
      return raw ? (JSON.parse(raw) as Lesson[]) : [];
    } catch {
      return [];
    }
  },

  saveBody: (id: number, content: string) =>
    AsyncStorage.setItem(KEYS.body(id), content),

  loadBody: async (id: number): Promise<string | null> => {
    try {
      return await AsyncStorage.getItem(KEYS.body(id));
    } catch {
      return null;
    }
  },

  invalidate: () => AsyncStorage.removeItem(KEYS.list),
};
