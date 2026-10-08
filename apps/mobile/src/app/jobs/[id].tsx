import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { router, Stack, useLocalSearchParams } from 'expo-router';
import { Check, Share2, Trash2, X } from 'lucide-react-native';
import { useRef, useState } from 'react';
import { ActivityIndicator, Alert, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { Job } from '@/api/client';
import { useApi } from '@/api/provider';
import { formatWhen, isFinished, type StageState, stageStates } from '@/jobs/status';
import { ExportSheet } from '@/score/ExportSheet';
import { type ExportFormat, fileName, shareBase64, shareDownload, sharePdf } from '@/score/exports';
import { type ScoreHandle, ScoreView } from '@/score/ScoreView';
import { colors, fonts, space } from '@/theme';
import { Card, IconButton, Text } from '@/ui';
import { ProgressRing } from '@/ui/ProgressRing';

/** One transcription: its progress, live, then its score. */
export default function JobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const api = useApi();
  const queryClient = useQueryClient();
  const [exporting, setExporting] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.deleteJob(id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ['job', id] });
      void queryClient.invalidateQueries({ queryKey: ['jobs'] });
      router.back();
    },
    onError: (error) => Alert.alert("Couldn't delete it", error.message),
  });
  const job = useQuery({
    queryKey: ['job', id],
    queryFn: () => api.getJob(id),
    // Poll every 2 s while the worker runs it; stop once it's finished.
    refetchInterval: (query) =>
      query.state.data && isFinished(query.state.data.status) ? false : 2000,
  });

  if (job.isPending) {
    return <ActivityIndicator color={colors.accent} style={styles.loading} />;
  }
  if (job.isError) {
    return <Text style={styles.error}>{job.error.message}</Text>;
  }

  const instrument = job.data.options.instrument === 'guitar' ? 'Guitar' : 'Piano';
  const title = job.data.name ?? `${instrument} take`;
  const confirmDelete = () =>
    Alert.alert(
      `Delete “${title}”?`,
      "This removes the score and the recording. It still counts towards this month's transcriptions.",
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: () => remove.mutate() },
      ],
    );
  const hasScore = job.data.outputs !== null;
  return (
    <SafeAreaView edges={['bottom']} style={styles.screen}>
      <Stack.Screen
        options={{
          headerTitle: title,
          headerRight: () => (
            <View style={styles.headerActions}>
              {hasScore && (
                <IconButton label="Export and share" onPress={() => setExporting(true)}>
                  <Share2 color={colors.text} size={22} />
                </IconButton>
              )}
              <IconButton label="Delete" onPress={confirmDelete} disabled={remove.isPending}>
                {remove.isPending ? (
                  <ActivityIndicator color={colors.dangerText} />
                ) : (
                  <Trash2 color={colors.dangerText} size={22} />
                )}
              </IconButton>
            </View>
          ),
        }}
      />
      {job.data.outputs ? (
        <Score
          job={job.data}
          outputs={job.data.outputs}
          exporting={exporting}
          onCloseExport={() => setExporting(false)}
          title={title}
          subtitle={`${instrument} · ${formatWhen(job.data.created_at)}`}
        />
      ) : (
        <Progress job={job.data} />
      )}
    </SafeAreaView>
  );
}

function Progress({ job }: { job: Job }) {
  const stages = stageStates(job);
  const settled = stages.filter((s) => s.state === 'done' || s.state === 'skipped').length;
  const current = stages.find((s) => s.state === 'running');
  const failed = job.status === 'failed';
  const headline = failed
    ? "Couldn't transcribe this one"
    : job.status === 'queued' && !current
      ? 'Waiting for a free worker…'
      : `${current?.label ?? 'Starting'}…`;

  return (
    <ScrollView contentContainerStyle={styles.progress}>
      <View style={styles.hero}>
        <ProgressRing fraction={settled / stages.length}>
          <Text style={styles.percent}>
            {failed ? '–' : `${Math.round((100 * settled) / stages.length)}%`}
          </Text>
        </ProgressRing>
        <Text variant="heading" style={styles.headline} testID="job-headline">
          {headline}
        </Text>
        {!failed && (
          <Text variant="muted" style={styles.centered}>
            You can leave this screen: it keeps going, and your library shows when it&apos;s ready.
          </Text>
        )}
      </View>

      {job.error && (
        <Card style={styles.errorCard}>
          <Text style={styles.errorText}>
            {job.error.message ?? 'Something went wrong while transcribing.'}
          </Text>
        </Card>
      )}

      <Card style={styles.steps}>
        {stages.map(({ label, state, seconds }) => (
          <View key={label} style={styles.step} testID={`stage-${state}`}>
            <StepMark state={state} />
            <Text
              style={[
                styles.stepLabel,
                state === 'running' && styles.stepCurrent,
                state === 'waiting' && styles.muted,
              ]}
            >
              {label}
            </Text>
            {seconds !== undefined && <Text variant="mono">{seconds.toFixed(1)} s</Text>}
          </View>
        ))}
      </Card>
    </ScrollView>
  );
}

function StepMark({ state }: { state: StageState }) {
  switch (state) {
    case 'done':
      return (
        <View style={[styles.mark, styles.markDone]}>
          <Check color={colors.background} size={16} strokeWidth={3} />
        </View>
      );
    case 'failed':
      return (
        <View style={[styles.mark, styles.markFailed]}>
          <X color={colors.background} size={16} strokeWidth={3} />
        </View>
      );
    case 'running':
      return <View style={[styles.mark, styles.markRunning]} />;
    default:
      return <View style={[styles.mark, styles.markWaiting]} />;
  }
}

/**
 * A finished job's score. Guitar jobs use the version with a TAB staff. Presigned links expire in
 * 15 minutes, but the score is fetched once per version and cached.
 */
function Score({
  job,
  outputs,
  exporting,
  onCloseExport,
  title,
  subtitle,
}: {
  job: Job;
  outputs: NonNullable<Job['outputs']>;
  exporting: boolean;
  onCloseExport: () => void;
  title: string;
  subtitle: string;
}) {
  const scoreView = useRef<ScoreHandle>(null);
  const source = outputs.tab_musicxml ?? outputs.musicxml;
  const guitar = job.options.instrument === 'guitar';
  const formats: ExportFormat[] = [
    'pdf',
    ...(guitar ? (['guitarPro'] as const) : []),
    'musicxml',
    ...(outputs.midi ? (['midi'] as const) : []),
  ];

  const onExport = async (format: ExportFormat) => {
    const name = fileName(title, format);
    const view = scoreView.current;
    switch (format) {
      case 'musicxml':
        return shareDownload(source, name, format);
      case 'midi':
        return outputs.midi ? shareDownload(outputs.midi, name, format) : undefined;
      case 'guitarPro':
        if (!view) throw new Error('the score is still loading');
        return shareBase64(await view.guitarPro(), name, format);
      case 'pdf':
        if (!view) throw new Error('the score is still loading');
        return sharePdf(await view.printable(), name);
    }
  };
  const musicXml = useQuery({
    queryKey: ['score', job.id, outputs.version],
    queryFn: async () => {
      const response = await fetch(source.url, { headers: source.headers });
      if (!response.ok) {
        throw new Error(`couldn't download the score (HTTP ${response.status})`);
      }
      return response.text();
    },
    staleTime: Infinity,
  });

  return (
    <View style={styles.score}>
      <ExportSheet
        visible={exporting}
        formats={formats}
        onExport={onExport}
        onClose={onCloseExport}
      />
      <Text variant="muted" style={styles.subtitle}>
        {subtitle}
      </Text>
      {musicXml.isPending ? (
        <ActivityIndicator color={colors.accent} style={styles.loading} />
      ) : musicXml.isError ? (
        <Text style={styles.error}>{musicXml.error.message}</Text>
      ) : (
        <ScoreView
          ref={scoreView}
          musicXml={musicXml.data}
          hasTab={outputs.tab_musicxml !== null}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  loading: { marginTop: 48 },
  error: { color: colors.dangerText, padding: space.xl },
  progress: { padding: space.xl, gap: space.xl },
  hero: { alignItems: 'center', gap: space.md, paddingVertical: space.lg },
  percent: { fontFamily: fonts.monoBold, fontSize: 36 },
  headline: { fontSize: 22, textAlign: 'center' },
  centered: { textAlign: 'center', paddingHorizontal: space.lg, lineHeight: 20 },
  errorCard: { borderColor: colors.danger },
  errorText: { color: colors.dangerText },
  steps: { paddingVertical: space.sm },
  step: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 10 },
  stepLabel: { flex: 1 },
  stepCurrent: { fontFamily: fonts.bodySemiBold },
  muted: { color: colors.muted },
  mark: {
    width: 28,
    height: 28,
    borderRadius: 14,
    alignItems: 'center',
    justifyContent: 'center',
  },
  markDone: { backgroundColor: colors.success },
  markFailed: { backgroundColor: colors.danger },
  markRunning: { borderWidth: 3, borderColor: colors.accent },
  markWaiting: { borderWidth: 2, borderColor: colors.faint },
  score: { flex: 1 },
  headerActions: { flexDirection: 'row' },
  subtitle: { textAlign: 'center', paddingBottom: space.md },
});
