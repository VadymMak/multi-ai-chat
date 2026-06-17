import { useState, useRef, useCallback } from "react";
import { Audio } from "expo-av";
import { Alert, Platform } from "react-native";
import { api } from "../lib/api";

interface Options {
  language?: string;
  onTranscript: (text: string) => void;
}

export function useVoiceRecorder({ language = "ru", onTranscript }: Options) {
  const [isRecording, setIsRecording] = useState(false);
  const [isTranscribing, setIsTranscribing] = useState(false);
  const recordingRef = useRef<Audio.Recording | null>(null);

  const startRecording = useCallback(async () => {
    try {
      const { status } = await Audio.requestPermissionsAsync();
      if (status !== "granted") {
        Alert.alert(
          "Permission required",
          "Microphone access is needed to record voice notes."
        );
        return;
      }

      // iOS only — these options don't exist on Android and can throw
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
      Alert.alert("Error", "Could not start recording. Please try again.");
    }
  }, []);

  const stopAndTranscribe = useCallback(async () => {
    const recording = recordingRef.current;
    if (!recording) return;

    setIsRecording(false);
    setIsTranscribing(true);

    try {
      await recording.stopAndUnloadAsync();
      if (Platform.OS === "ios") {
        await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
      }

      const uri = recording.getURI();
      recordingRef.current = null;
      if (!uri) throw new Error("No URI after recording");

      const formData = new FormData();
      formData.append("audio", {
        uri,
        type: "audio/m4a",
        name: "voice.m4a",
      } as unknown as Blob);
      formData.append("language", language);

      const { data } = await api.post("/api/voice", formData, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 30000,
      });

      if (data.success && data.data?.transcript) {
        onTranscript(data.data.transcript);
      }
    } catch (err) {
      console.error("[useVoiceRecorder] transcribe error:", err);
      Alert.alert("Error", "Could not transcribe audio. Please type your note instead.");
    } finally {
      setIsTranscribing(false);
    }
  }, [language, onTranscript]);

  const toggle = useCallback(() => {
    if (isRecording) stopAndTranscribe();
    else startRecording();
  }, [isRecording, startRecording, stopAndTranscribe]);

  return { isRecording, isTranscribing, toggle };
}
