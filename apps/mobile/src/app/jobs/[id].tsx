import { useQuery } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { Job } from '@/api/client';
import { useApi } from '@/api/provider';
import { isFinished, STATUS_LABELS, type StageState, stageStates } from '@/jobs/status';
import { ScoreView } from '@/score/ScoreView';

const ICONS: Record<StageState, string> = {
  waiting: '○',
  running: '◐',
  done: '✓',
  skipped: '–',
  failed: '✕',
};

/** One transcription: its pipeline stages, live, until it's ready or has failed. */
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
    return <ActivityIndicator style={styles.loading} />;
  }
  if (job.isError) {
    return <Text style={[styles.container, styles.error]}>{job.error.message}</Text>;
  }

  if (job.data.outputs) {
    return <Score outputs={job.data.outputs} jobId={job.data.id} />;
  }

  const { status, options, error } = job.data;
  const running = !isFinished(status);
  return (
    <ScrollView contentContainerStyle={styles.container}>
      <View style={styles.header}>
        {running && <ActivityIndicator />}
        <Text style={styles.status} testID="job-status">
          {STATUS_LABELS[status]}
        </Text>
      </View>
      <Text style={styles.muted}>
        {options.instrument === 'guitar' ? 'Guitar' : 'Piano'}
        {running && ' · this takes about a minute for a short clip'}
      </Text>

      <View style={styles.stages}>
        {stageStates(job.data).map(({ label, state, seconds }) => (
          <View key={label} style={styles.stage} testID={`stage-${state}`}>
            <Text style={[styles.icon, styles[state]]}>{ICONS[state]}</Text>
            <Text style={[styles.stageLabel, state === 'waiting' && styles.muted]}>{label}</Text>
            {seconds !== undefined && <Text style={styles.muted}>{seconds.toFixed(1)} s</Text>}
          </View>
        ))}
      </View>

      {error && (
        <Text style={styles.error}>
          {error.message ?? 'Something went wrong while transcribing.'} ({error.code})
        </Text>
      )}
    </ScrollView>
  );
}

/**
 * A finished job's score. Guitar jobs show the version with a TAB staff under the notation.
 * Presigned links expire in 15 minutes, but the score is fetched once per version and cached.
 */
function Score({ outputs, jobId }: { outputs: NonNullable<Job['outputs']>; jobId: string }) {
  const source = outputs.tab_musicxml ?? outputs.musicxml;
  const musicXml = useQuery({
    queryKey: ['score', jobId, outputs.version],
    queryFn: async () => {
      const response = await fetch(source.url, { headers: source.headers });
      if (!response.ok) {
        throw new Error(`couldn't download the score (HTTP ${response.status})`);
      }
      return response.text();
    },
    staleTime: Infinity,
  });

  if (musicXml.isPending) {
    return <ActivityIndicator style={styles.loading} />;
  }
  if (musicXml.isError) {
    return <Text style={[styles.container, styles.error]}>{musicXml.error.message}</Text>;
  }
  return <ScoreView musicXml={musicXml.data} />;
}

const styles = StyleSheet.create({
  loading: { marginTop: 48 },
  container: { padding: 24, gap: 16 },
  header: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  status: { fontSize: 24, fontWeight: '600' },
  stages: { gap: 12, marginTop: 8 },
  stage: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  icon: { width: 24, fontSize: 18, textAlign: 'center' },
  stageLabel: { flex: 1, fontSize: 16 },
  waiting: { opacity: 0.4 },
  running: { color: '#1f6feb' },
  done: { color: '#1a7f37' },
  skipped: { opacity: 0.4 },
  failed: { color: '#b00020' },
  muted: { opacity: 0.6 },
  error: { color: '#b00020' },
});
