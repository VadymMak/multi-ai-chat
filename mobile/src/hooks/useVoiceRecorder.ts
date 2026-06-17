import { useState, useRef, useCallback } from "react";
import {
  useAudioRecorder,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  RecordingPresets,
} from "expo-audio";
import { Alert, Platform } from "react-native";

interface Options {
  onRecordingComplete: (uri: string) => void;
}

export function useVoiceRecorder({ onRecordingComplete }: Options) {
  const [isRecording, setIsRecording] = useState(false);
  // Guard against concurrent startRecording calls (hold-to-record fast taps)
  const isStartingRef = useRef(false);

  // Single recorder instance; expo-audio manages lifecycle via useReleasingSharedObject
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY);

  const startRecording = useCallback(async () => {
    if (isStartingRef.current || recorder.isRecording) return;
    isStartingRef.current = true;

    try {
      const { granted } = await requestRecordingPermissionsAsync();
      if (!granted) {
        Alert.alert("Нет доступа", "Для записи нужен доступ к микрофону.");
        return;
      }

      if (Platform.OS === "ios") {
        await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
      }

      await recorder.prepareToRecordAsync();
      recorder.record();
      setIsRecording(true);
    } catch (err) {
      console.error("[useVoiceRecorder] start error:", err);
      Alert.alert("Ошибка", "Не удалось начать запись.");
    } finally {
      isStartingRef.current = false;
    }
  }, [recorder]);

  const stopRecording = useCallback(async () => {
    if (!recorder.isRecording) return;

    setIsRecording(false);
    try {
      await recorder.stop();
      if (Platform.OS === "ios") {
        await setAudioModeAsync({ allowsRecording: false, playsInSilentMode: true });
      }
      const uri = recorder.uri;
      if (uri) onRecordingComplete(uri);
    } catch (err) {
      console.error("[useVoiceRecorder] stop error:", err);
    }
  }, [recorder, onRecordingComplete]);

  return { isRecording, startRecording, stopRecording };
}
