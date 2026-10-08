import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useAudioPlayer, useAudioPlayerStatus } from 'expo-audio';
import { router } from 'expo-router';
import { ArrowRight, ChevronDown, FileAudio, Pause, Play } from 'lucide-react-native';
import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { Instrument, Tuning } from '@/api/client';
import { useApi } from '@/api/provider';
import { type AudioClip, formatDuration, formatSize } from '@/audio/clip';
import { LevelBars } from '@/audio/LevelBars';
import { pickAudioFile } from '@/audio/pickAudioFile';
import { Recorder } from '@/audio/Recorder';
import { type Step, startTranscription, uploadFile } from '@/jobs/transcribe';
import { colors, fonts, radius, space } from '@/theme';
import { Button, Card, Chip, IconButton, Row, Segmented, Text } from '@/ui';
import { OptionSheet } from '@/ui/OptionSheet';

const INSTRUMENTS: { value: Instrument; label: string }[] = [
  { value: 'guitar', label: 'Guitar' },
  { value: 'piano', label: 'Piano' },
];
const TUNINGS: { value: Tuning; label: string; detail: string }[] = [
  { value: 'standard', label: 'Standard tuning', detail: 'E A D G B E' },
  { value: 'drop_d', label: 'Drop D tuning', detail: 'D A D G B E' },
];
const CAPOS = Array.from({ length: 13 }, (_, fret) => ({
  value: fret,
  label: fret === 0 ? 'No capo' : `Capo on fret ${fret}`,
}));

function stepLabel(step: Step | null): string {
  switch (step?.step) {
    case 'uploading':
      return `Uploading ${Math.round(step.fraction * 100)}%`;
    case 'submitting':
      return 'Starting…';
    default:
      return 'Preparing…';
  }
}

/** New take: choose the instrument, record or import, review, then transcribe. */
export default function NewTake() {
  const [instrument, setInstrument] = useState<Instrument>('guitar');
  const [tuning, setTuning] = useState<Tuning>('standard');
  const [capo, setCapo] = useState(0);
  const [sheet, setSheet] = useState<'tuning' | 'capo' | null>(null);
  const [clip, setClip] = useState<AudioClip | null>(null);
  const [pickError, setPickError] = useState<string | null>(null);

  const importFile = async () => {
    setPickError(null);
    const result = await pickAudioFile();
    if (result.kind === 'picked') {
      setClip(result.clip);
    } else if (result.kind === 'unsupported') {
      setPickError(`${result.name} isn't a supported audio file (M4A, MP3, WAV, FLAC, OGG, AAC).`);
    }
  };

  const guitar = instrument === 'guitar';
  if (clip) {
    return (
      <Review
        clip={clip}
        instrument={instrument}
        tuning={guitar ? tuning : undefined}
        capo={guitar ? capo : undefined}
        onDiscard={() => setClip(null)}
      />
    );
  }

  return (
    <SafeAreaView edges={['bottom']} style={styles.screen}>
      <View style={styles.choices}>
        <Segmented
          label="Instrument"
          options={INSTRUMENTS}
          value={instrument}
          onChange={setInstrument}
        />
        {guitar && (
          <View style={styles.chips}>
            <Chip
              label={TUNINGS.find((t) => t.value === tuning)?.label ?? ''}
              trailing={<ChevronDown color={colors.text} size={14} />}
              onPress={() => setSheet('tuning')}
            />
            <Chip
              label={CAPOS[capo]?.label ?? ''}
              trailing={<ChevronDown color={colors.text} size={14} />}
              onPress={() => setSheet('capo')}
            />
          </View>
        )}
      </View>
      <Recorder onRecorded={setClip} onImport={importFile} />
      {pickError && <Text style={styles.error}>{pickError}</Text>}

      <OptionSheet
        visible={sheet === 'tuning'}
        title="Tuning"
        options={TUNINGS}
        value={tuning}
        onChange={setTuning}
        onClose={() => setSheet(null)}
      />
      <OptionSheet
        visible={sheet === 'capo'}
        title="Capo"
        options={CAPOS}
        value={capo}
        onChange={setCapo}
        onClose={() => setSheet(null)}
      />
    </SafeAreaView>
  );
}

/** Listen back, name it, and send it off. */
function Review({
  clip,
  instrument,
  tuning,
  capo,
  onDiscard,
}: {
  clip: AudioClip;
  instrument: Instrument;
  tuning?: Tuning;
  capo?: number;
  onDiscard: () => void;
}) {
  const api = useApi();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });
  const player = useAudioPlayer(clip.uri);
  const playback = useAudioPlayerStatus(player);
  const [name, setName] = useState('');
  const [step, setStep] = useState<Step | null>(null);
  const label = instrument === 'guitar' ? 'Guitar' : 'Piano';

  const transcribe = useMutation({
    mutationFn: () =>
      startTranscription(
        api,
        clip,
        { instrument, tuning, capo, name: name.trim() || undefined },
        uploadFile,
        setStep,
      ),
    onSuccess: (job) => {
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      void queryClient.invalidateQueries({ queryKey: ['me'] });
      router.replace({ pathname: '/jobs/[id]', params: { id: job.id } });
    },
  });

  const togglePlayback = () => {
    if (playback.playing) {
      player.pause();
    } else {
      if (playback.didJustFinish || playback.currentTime >= playback.duration) {
        void player.seekTo(0);
      }
      player.play();
    }
  };
  const progress = playback.duration > 0 ? playback.currentTime / playback.duration : 0;
  const remaining = me.data ? me.data.jobs_per_month - me.data.jobs_this_month : undefined;

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.screen}
    >
      <ScrollView contentContainerStyle={styles.review} keyboardShouldPersistTaps="handled">
        <Card style={styles.player}>
          {clip.waveform && clip.waveform.length > 0 ? (
            <LevelBars levels={clip.waveform} count={52} height={88} progress={progress} />
          ) : (
            <View style={styles.file}>
              <FileAudio color={colors.accent} size={28} />
              <View style={styles.fileText}>
                <Text variant="label" numberOfLines={1}>
                  {clip.name}
                </Text>
                <Text variant="muted">{formatSize(clip.sizeBytes)}</Text>
              </View>
            </View>
          )}
          <View style={styles.transport}>
            <Text variant="mono">
              {formatDuration(playback.currentTime * 1000)} /{' '}
              {formatDuration((playback.duration || (clip.durationMs ?? 0) / 1000) * 1000)}
            </Text>
            <IconButton
              label={playback.playing ? 'Pause' : 'Play your take'}
              size={56}
              onPress={togglePlayback}
              style={styles.play}
            >
              {playback.playing ? (
                <Pause color={colors.background} fill={colors.background} size={22} />
              ) : (
                <Play color={colors.background} fill={colors.background} size={22} />
              )}
            </IconButton>
            <View style={styles.transportSpacer} />
          </View>
        </Card>

        <View style={styles.field}>
          <Text variant="muted" style={styles.fieldLabel} nativeID="take-name">
            Name
          </Text>
          <TextInput
            accessibilityLabelledBy="take-name"
            value={name}
            onChangeText={setName}
            placeholder={`${label} take`}
            placeholderTextColor={colors.faint}
            maxLength={120}
            returnKeyType="done"
            style={styles.input}
          />
        </View>

        <Card style={styles.summary}>
          <Row label="Instrument" last={tuning === undefined}>
            <Text variant="label">{label}</Text>
          </Row>
          {tuning !== undefined && (
            <>
              <Row label="Tuning">
                <Text variant="label">{TUNINGS.find((t) => t.value === tuning)?.label}</Text>
              </Row>
              <Row label="Capo" last>
                <Text variant="label">{capo ? `Fret ${capo}` : 'None'}</Text>
              </Row>
            </>
          )}
        </Card>
      </ScrollView>

      <SafeAreaView edges={['bottom']} style={styles.actions}>
        {transcribe.isError && <Text style={styles.error}>{transcribe.error.message}</Text>}
        <Button
          title={transcribe.isPending ? stepLabel(step) : 'Transcribe'}
          icon={transcribe.isPending ? undefined : <ArrowRight color={colors.onAccent} size={20} />}
          loading={transcribe.isPending}
          disabled={transcribe.isPending}
          onPress={() => {
            player.pause();
            transcribe.mutate();
          }}
        />
        <Button
          title="Record again"
          kind="secondary"
          disabled={transcribe.isPending}
          onPress={onDiscard}
        />
        {remaining !== undefined && (
          <Text variant="caption" style={styles.centered}>
            Uses 1 of your {remaining} remaining transcriptions this month
          </Text>
        )}
      </SafeAreaView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  choices: { paddingHorizontal: space.xl, paddingTop: space.sm, gap: space.md },
  chips: { flexDirection: 'row', gap: space.sm },
  error: { color: colors.dangerText, textAlign: 'center', paddingHorizontal: space.xl },
  review: { padding: space.xl, gap: space.xl },
  player: { padding: space.lg, gap: space.lg },
  file: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  fileText: { flex: 1, gap: 2 },
  transport: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' },
  transportSpacer: { width: 80 },
  play: { backgroundColor: colors.text },
  field: { gap: space.sm },
  fieldLabel: { fontFamily: fonts.bodySemiBold },
  input: {
    height: 52,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    color: colors.text,
    fontFamily: fonts.body,
    fontSize: 16,
  },
  summary: { padding: 0 },
  actions: { paddingHorizontal: space.xl, paddingTop: space.sm, gap: 10 },
  centered: { textAlign: 'center', marginBottom: space.sm },
});
