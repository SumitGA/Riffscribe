import {
  RecordingPresets,
  requestRecordingPermissionsAsync,
  setAudioModeAsync,
  useAudioRecorder,
} from 'expo-audio';
import { File } from 'expo-file-system';
import { FolderOpen } from 'lucide-react-native';
import { useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { colors, fonts, space } from '@/theme';
import { IconButton, Text } from '@/ui';

import { type AudioClip, formatDuration, MAX_RECORDING_MS } from './clip';
import { LevelBars, levelFromDecibels } from './LevelBars';

const METER_BARS = 40;
const POLL_MS = 100;

/**
 * Records from the microphone (AAC in .m4a) with a live level meter; stops by itself at the free
 * tier's limit. The meter's history becomes the clip's waveform for the review screen.
 */
export function Recorder({
  onRecorded,
  onImport,
}: {
  onRecorded: (clip: AudioClip) => void;
  onImport: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [recording, setRecording] = useState(false);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [levels, setLevels] = useState<number[]>([]);
  const waveform = useRef<number[]>([]);
  const startedAt = useRef(0);
  const onRecordedRef = useRef(onRecorded);
  useEffect(() => {
    onRecordedRef.current = onRecorded;
  });

  // Fires when recording ends, whether the user stopped it or it reached the limit.
  const recorder = useAudioRecorder(
    { ...RecordingPresets.HIGH_QUALITY, isMeteringEnabled: true },
    (status) => {
      if (status.hasError) {
        setRecording(false);
        setError(status.error ?? 'Recording failed. Try again.');
      } else if (status.isFinished && status.url) {
        setRecording(false);
        void setAudioModeAsync({ allowsRecording: false });
        onRecordedRef.current({
          uri: status.url,
          name: 'Recording.m4a',
          contentType: 'audio/mp4',
          sizeBytes: new File(status.url).size ?? 0,
          durationMs: Math.min(Date.now() - startedAt.current, MAX_RECORDING_MS),
          waveform: waveform.current,
        });
      }
    },
  );

  // Sample time and input level while recording.
  useEffect(() => {
    if (!recording) {
      return;
    }
    const timer = setInterval(() => {
      const status = recorder.getStatus();
      const level = levelFromDecibels(status.metering);
      waveform.current.push(level);
      setElapsedMs(status.durationMillis);
      setLevels((previous) => [...previous.slice(1 - METER_BARS), level]);
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [recording, recorder]);

  const start = async () => {
    setError(null);
    const permission = await requestRecordingPermissionsAsync();
    if (!permission.granted) {
      setError('Riffscribe needs the microphone to record. Allow it in Settings.');
      return;
    }
    await setAudioModeAsync({ allowsRecording: true, playsInSilentMode: true });
    await recorder.prepareToRecordAsync();
    waveform.current = [];
    setLevels([]);
    setElapsedMs(0);
    startedAt.current = Date.now();
    recorder.record({ forDuration: MAX_RECORDING_MS / 1000 });
    setRecording(true);
  };

  return (
    <View style={styles.container}>
      <View style={styles.center}>
        <View style={styles.statusRow}>
          {recording && <View style={styles.dot} />}
          <Text style={[styles.status, recording && styles.statusRecording]}>
            {recording ? 'Recording' : 'Ready when you are'}
          </Text>
        </View>
        <Text variant="timer" testID="recording-time">
          {formatDuration(elapsedMs)}
        </Text>
        <Text variant="muted">
          of {formatDuration(MAX_RECORDING_MS)} · single notes give the cleanest tab
        </Text>
        <LevelBars levels={levels} count={METER_BARS} height={96} />
        {error && <Text style={styles.error}>{error}</Text>}
      </View>

      <View style={styles.controls}>
        <IconButton
          label="Import an audio file"
          filled
          size={56}
          onPress={onImport}
          disabled={recording}
        >
          <FolderOpen color={colors.text} size={22} />
        </IconButton>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={recording ? 'Stop recording' : 'Start recording'}
          onPress={recording ? () => void recorder.stop() : start}
          style={[styles.record, recording && styles.recordActive]}
        >
          <View style={recording ? styles.stopIcon : styles.recordIcon} />
        </Pressable>
        <View style={styles.spacer} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, justifyContent: 'space-between' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: space.md },
  statusRow: { flexDirection: 'row', alignItems: 'center', gap: space.sm },
  dot: { width: 10, height: 10, borderRadius: 5, backgroundColor: colors.danger },
  status: { fontFamily: fonts.bodySemiBold, fontSize: 14, color: colors.muted },
  statusRecording: { color: colors.danger },
  error: { color: colors.dangerText, textAlign: 'center' },
  controls: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: space.xl,
  },
  spacer: { width: 56 },
  record: {
    width: 96,
    height: 96,
    borderRadius: 48,
    borderWidth: 4,
    borderColor: colors.danger,
    alignItems: 'center',
    justifyContent: 'center',
  },
  recordActive: { backgroundColor: 'rgba(255, 107, 107, 0.12)' },
  recordIcon: { width: 64, height: 64, borderRadius: 32, backgroundColor: colors.danger },
  stopIcon: { width: 34, height: 34, borderRadius: 8, backgroundColor: colors.danger },
});
