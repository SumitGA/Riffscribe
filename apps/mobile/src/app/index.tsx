import { useClerk } from '@clerk/expo';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'expo-router';
import { FlatList, Pressable, RefreshControl, StyleSheet, Text, View } from 'react-native';

import type { JobSummary } from '@/api/client';
import { useApi } from '@/api/provider';
import { formatWhen, isFinished, STATUS_LABELS } from '@/jobs/status';

/** Home: start a transcription, and the user's jobs, newest first. */
export default function Home() {
  const api = useApi();
  const { signOut } = useClerk();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.listJobs(),
    // Keep statuses fresh while anything is still being transcribed.
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => !isFinished(job.status)) ? 3000 : false,
  });

  const onSignOut = async () => {
    await signOut();
    queryClient.clear(); // the next user must not see this one's cached data
  };

  return (
    <FlatList
      contentContainerStyle={styles.container}
      data={jobs.data?.jobs ?? []}
      keyExtractor={(job) => job.id}
      refreshControl={
        <RefreshControl refreshing={jobs.isRefetching} onRefresh={() => void jobs.refetch()} />
      }
      ListHeaderComponent={
        <View style={styles.header}>
          <Link href="/new" asChild>
            <Pressable accessibilityRole="button" style={styles.primary}>
              <Text style={styles.primaryText}>New transcription</Text>
            </Pressable>
          </Link>
          <Text style={styles.muted} testID="quota">
            {me.isError
              ? `Can't reach the API: ${me.error.message}`
              : me.data
                ? `${me.data.jobs_this_month} of ${me.data.jobs_per_month} transcriptions used this month`
                : ' '}
          </Text>
          {jobs.isError && <Text style={styles.error}>{jobs.error.message}</Text>}
        </View>
      }
      ListEmptyComponent={
        jobs.isSuccess ? (
          <Text style={[styles.muted, styles.empty]}>
            Nothing yet. Record a riff or pick a file to get your first score.
          </Text>
        ) : null
      }
      renderItem={({ item }) => <JobRow job={item} />}
      ListFooterComponent={
        <Pressable accessibilityRole="button" onPress={onSignOut} style={styles.signOut}>
          <Text style={styles.link}>Sign out</Text>
        </Pressable>
      }
    />
  );
}

function JobRow({ job }: { job: JobSummary }) {
  return (
    <Link href={{ pathname: '/jobs/[id]', params: { id: job.id } }} asChild>
      <Pressable accessibilityRole="button" style={styles.row}>
        <Text style={styles.rowTitle}>{job.instrument === 'guitar' ? 'Guitar' : 'Piano'}</Text>
        <Text style={styles.muted}>{formatWhen(job.created_at)}</Text>
        <Text style={[styles.badge, styles[job.status]]}>{STATUS_LABELS[job.status]}</Text>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  container: { padding: 16, gap: 10 },
  header: { gap: 12, marginBottom: 8 },
  primary: {
    backgroundColor: '#1f6feb',
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: 'center',
  },
  primaryText: { color: 'white', fontSize: 18, fontWeight: '600' },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#ddd',
  },
  rowTitle: { fontSize: 16, fontWeight: '600' },
  badge: { marginLeft: 'auto', fontWeight: '600' },
  pending_upload: { opacity: 0.5 },
  queued: { color: '#9a6700' },
  running: { color: '#1f6feb' },
  succeeded: { color: '#1a7f37' },
  failed: { color: '#b00020' },
  muted: { opacity: 0.6 },
  empty: { textAlign: 'center', marginTop: 32 },
  error: { color: '#b00020' },
  link: { color: '#1f6feb' },
  signOut: { alignSelf: 'center', padding: 16 },
});
