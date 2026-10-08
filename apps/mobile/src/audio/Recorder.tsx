import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
  useAudioRecorderState,
} from 'expo-audio';
import { File } from 'expo-file-system';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { type AudioClip, formatDuration, MAX_RECORDING_MS } from './clip';

/** Records from the microphone (AAC in .m4a); stops by itself at the free tier's limit. */
export function Recorder({ onRecorded }: { onRecorded: (clip: AudioClip) => void }) {
  const [error, setError] = useState<string | null>(null);
  const startedAt = useRef(0);
  const onRecordedRef = useRef(onRecorded);
  useEffect(() => {
    onRecordedRef.current = onRecorded;
  });

  // Fires when recording ends, whether the user stopped it or it reached the limit.
  const recorder = useAudioRecorder(RecordingPresets.HIGH_QUALITY, (status) => {
    if (status.hasError) {
      setError(status.error ?? 'Recording failed. Try again.');
    } else if (status.isFinished && status.url) {
      void setAudioModeAsync({ allowsRecording: false });
      onRecordedRef.current({
        uri: status.url,
        name: `Recording ${new Date().toLocaleTimeString()}.m4a`,
        contentType: 'audio/mp4',
        sizeBytes: new File(status.url).size ?? 0,
        durationMs: Math.min(Date.now() - startedAt.current, MAX_RECORDING_MS),
      });
    }
  });
  const state = useAudioRecorderState(recorder, 250);

  const start = async () => {
    setError(null);
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      setError('Riffscribe needs the microphone to record. Allow it in Settings.');
      return;
    }
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    startedAt.current = Date.now();
    recorder.record({ forDuration: MAX_RECORDING_MS / 1000 });
  };

  const stop = () => recorder.stop();

  return (
    <View style={styles.container}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={state.isRecording ? 'Stop recording' : 'Start recording'}
        onPress={state.isRecording ? stop : start}
        style={[styles.button, state.isRecording && styles.recording]}
      >
        <View style={state.isRecording ? styles.stopIcon : styles.recordIcon} />
      </Pressable>
      <Text style={styles.timer} testID="recording-time">
        {state.isRecording
          ? `${formatDuration(state.durationMillis)} / ${formatDuration(MAX_RECORDING_MS)}`
          : 'Tap to record'}
      </Text>
      {error && <Text style={styles.error}>{error}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignItems: 'center', gap: 12 },
  button: {
    width: 88,
    height: 88,
    borderRadius: 44,
    borderWidth: 4,
    borderColor: '#d33',
    alignItems: 'center',
    justifyContent: 'center',
  },
  recording: { backgroundColor: '#fdecec' },
  recordIcon: { width: 60, height: 60, borderRadius: 30, backgroundColor: '#d33' },
  stopIcon: { width: 32, height: 32, borderRadius: 4, backgroundColor: '#d33' },
  timer: { fontSize: 18, fontVariant: ['tabular-nums'] },
  error: { color: '#b00020', textAlign: 'center' },
});
