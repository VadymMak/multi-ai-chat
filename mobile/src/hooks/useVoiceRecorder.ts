import { useState, useRef, useCallback } from "react";
import { Audio } from "expo-av";
import { Alert, Platform } from "react-native";

interface Options {
  onRecordingComplete: (uri: string) => void;
}

export function useVoiceRecorder({ onRecordingComplete }: Options) {
  const [isRecording, setIsRecording] = useState(false);
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = useCallback(async () => {
    try {
      const { status } = await Audio.requestPermissionsAsync();
      if (status !== "granted") {
        Alert.alert("Нет доступа", "Для записи нужен доступ к микрофону.");
        return;
      }

      if (Platform.OS === "ios") {
        await Audio.setAudioModeAsync({
          allowsRecordingIOS: true,
          playsInSilentModeIOS: true,
        });
      }

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = recording;
      setIsRecording(true);
    } catch (err) {
      console.error("[useVoiceRecorder] start error:", err);
      Alert.alert("Ошибка", "Не удалось начать запись.");
    }
  }, []);

  const stopRecording = useCallback(async () => {
    const recording = recordingRef.current;
    if (!recording) return;

    setIsRecording(false);
    recordingRef.current = null;

    try {
      await recording.stopAndUnloadAsync();
      if (Platform.OS === "ios") {
        await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
      }
      const uri = recording.getURI();
      if (uri) onRecordingComplete(uri);
    } catch (err) {
      console.error("[useVoiceRecorder] stop error:", err);
    }
  }, [onRecordingComplete]);

  return { isRecording, startRecording, stopRecording };
}
