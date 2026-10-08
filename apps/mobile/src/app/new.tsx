import { useMutation, useQueryClient } from '@tanstack/react-query';
import { router } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Instrument } from '@/api/client';
import { useApi } from '@/api/provider';
import { type AudioClip, formatDuration, formatSize } from '@/audio/clip';
import { pickAudioFile } from '@/audio/pickAudioFile';
import { Recorder } from '@/audio/Recorder';
import { type Step, startTranscription, uploadFile } from '@/jobs/transcribe';

const INSTRUMENTS: { value: Instrument; label: string }[] = [
  { value: 'guitar', label: 'Guitar' },
  { value: 'piano', label: 'Piano' },
];

function stepLabel(step: Step | null): string {
  switch (step?.step) {
    case 'uploading':
      return `Uploading… ${Math.round(step.fraction * 100)}%`;
    case 'submitting':
      return 'Starting the transcription…';
    default:
      return 'Creating the job…';
  }
}

/** Record or choose audio, pick the instrument, and send it off to be transcribed. */
export default function NewTranscription() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [instrument, setInstrument] = useState<Instrument>('guitar');
  const [clip, setClip] = useState<AudioClip | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);
  const [step, setStep] = useState<Step | null>(null);

  const transcribe = useMutation({
    mutationFn: (audio: AudioClip) =>
      startTranscription(api, audio, instrument, uploadFile, setStep),
    onSuccess: (job) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['me'] });
      router.replace({ pathname: '/jobs/[id]', params: { id: job.id } });
    },
  });

  const chooseFile = async () => {
    setPickError(null);
    const result = await pickAudioFile();
    if (result.kind === 'picked') {
      setClip(result.clip);
    } else if (result.kind === 'unsupported') {
      setPickError(`${result.name} isn't a supported audio file (M4A, MP3, WAV, FLAC, OGG, AAC).`);
    }
  };

  return (
    <ScrollView contentContainerStyle={styles.container}>
      <Text style={styles.heading}>What are you playing?</Text>
      <View style={styles.segments} accessibilityRole="radiogroup">
        {INSTRUMENTS.map(({ value, label }) => (
          <Pressable
            key={value}
            accessibilityRole="radio"
            accessibilityState={{ selected: instrument === value }}
            onPress={() => setInstrument(value)}
            style={[styles.segment, instrument === value && styles.segmentSelected]}
          >
            <Text style={[styles.segmentText, instrument === value && styles.selectedText]}>
              {label}
            </Text>
          </Pressable>
        ))}
      </View>

      {clip ? (
        <View style={styles.card}>
          <Text style={styles.clipName} numberOfLines={1}>
            {clip.name}
          </Text>
          <Text style={styles.muted}>
            {[
              clip.durationMs !== undefined && formatDuration(clip.durationMs),
              formatSize(clip.sizeBytes),
            ]
              .filter(Boolean)
              .join(' · ')}
          </Text>
          {transcribe.isPending ? (
            <View style={styles.row}>
              <ActivityIndicator />
              <Text testID="progress">{stepLabel(step)}</Text>
            </View>
          ) : (
            <>
              <Pressable
                accessibilityRole="button"
                style={styles.primary}
                onPress={() => transcribe.mutate(clip)}
              >
                <Text style={styles.primaryText}>Transcribe</Text>
              </Pressable>
              <Pressable accessibilityRole="button" onPress={() => setClip(null)}>
                <Text style={styles.link}>Use different audio</Text>
              </Pressable>
            </>
          )}
          {transcribe.isError && <Text style={styles.error}>{transcribe.error.message}</Text>}
        </View>
      ) : (
        <>
          <Recorder onRecorded={setClip} />
          <Text style={styles.muted}>or</Text>
          <Pressable accessibilityRole="button" style={styles.secondary} onPress={chooseFile}>
            <Text style={styles.secondaryText}>Choose an audio file</Text>
          </Pressable>
          {pickError && <Text style={styles.error}>{pickError}</Text>}
          <Text style={styles.hint}>Solo {instrument}, up to 5 minutes.</Text>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { padding: 24, gap: 20, alignItems: 'center' },
  heading: { fontSize: 20, fontWeight: '600' },
  segments: {
    flexDirection: 'row',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#ccc',
    overflow: 'hidden',
  },
  segment: { paddingVertical: 10, paddingHorizontal: 28 },
  segmentSelected: { backgroundColor: '#1f6feb' },
  segmentText: { fontSize: 16 },
  selectedText: { color: 'white', fontWeight: '600' },
  card: {
    alignSelf: 'stretch',
    padding: 16,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#ddd',
    gap: 12,
  },
  clipName: { fontSize: 16, fontWeight: '600' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  primary: {
    backgroundColor: '#1f6feb',
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center',
  },
  primaryText: { color: 'white', fontSize: 17, fontWeight: '600' },
  secondary: {
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#1f6feb',
    paddingVertical: 12,
    paddingHorizontal: 24,
  },
  secondaryText: { color: '#1f6feb', fontSize: 16, fontWeight: '600' },
  link: { color: '#1f6feb', textAlign: 'center' },
  muted: { opacity: 0.6 },
  hint: { opacity: 0.6, marginTop: 8 },
  error: { color: '#b00020', textAlign: 'center' },
});
