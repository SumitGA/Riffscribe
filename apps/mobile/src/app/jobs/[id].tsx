import { useQuery } from '@tanstack/react-query';
import { Stack, useLocalSearchParams } from 'expo-router';
import { Check, X } from 'lucide-react-native';
import { ActivityIndicator, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { Job } from '@/api/client';
import { useApi } from '@/api/provider';
import { formatWhen, isFinished, type StageState, stageStates } from '@/jobs/status';
import { ScoreView } from '@/score/ScoreView';
import { colors, fonts, space } from '@/theme';
import { Card, Text } from '@/ui';
import { ProgressRing } from '@/ui/ProgressRing';

/** One transcription: its progress, live, then its score. */
export default function JobScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const api = useApi();
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
  return (
    <SafeAreaView edges={['bottom']} style={styles.screen}>
      <Stack.Screen options={{ headerTitle: title }} />
      {job.data.outputs ? (
        <Score
          job={job.data}
          outputs={job.data.outputs}
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
  subtitle,
}: {
  job: Job;
  outputs: NonNullable<Job['outputs']>;
  subtitle: string;
}) {
  const source = outputs.tab_musicxml ?? outputs.musicxml;
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
      <Text variant="muted" style={styles.subtitle}>
        {subtitle}
      </Text>
      {musicXml.isPending ? (
        <ActivityIndicator color={colors.accent} style={styles.loading} />
      ) : musicXml.isError ? (
        <Text style={styles.error}>{musicXml.error.message}</Text>
      ) : (
        <ScoreView musicXml={musicXml.data} hasTab={outputs.tab_musicxml !== null} />
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
  subtitle: { textAlign: 'center', paddingBottom: space.md },
});
