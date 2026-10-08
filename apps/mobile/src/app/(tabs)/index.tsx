import { useQuery } from '@tanstack/react-query';
import { Link } from 'expo-router';
import { Guitar, Piano } from 'lucide-react-native';
import { useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  StyleSheet,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import type { Instrument, JobStatus, JobSummary } from '@/api/client';
import { useApi } from '@/api/provider';
import { formatWhen, isFinished } from '@/jobs/status';
import { colors, fonts, radius, space } from '@/theme';
import { Card, Chip, ProgressBar, Text } from '@/ui';

type Filter = 'all' | Instrument;
const FILTERS: { value: Filter; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'guitar', label: 'Guitar' },
  { value: 'piano', label: 'Piano' },
];

const STATUS: Record<JobStatus, { label: string; color: string }> = {
  pending_upload: { label: 'Uploading', color: colors.muted },
  queued: { label: 'Queued', color: colors.accent },
  running: { label: 'Transcribing', color: colors.accent },
  succeeded: { label: 'Ready', color: colors.success },
  failed: { label: 'Failed', color: colors.dangerText },
};

/** Library: this month's quota and the user's transcriptions, newest first. */
export default function Library() {
  const api = useApi();
  const [filter, setFilter] = useState<Filter>('all');
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: () => api.listJobs(),
    // Keep statuses fresh while anything is still being transcribed.
    refetchInterval: (query) =>
      query.state.data?.jobs.some((job) => !isFinished(job.status)) ? 3000 : false,
  });
  const shown = (jobs.data?.jobs ?? []).filter(
    (job) => filter === 'all' || job.instrument === filter,
  );

  return (
    <SafeAreaView edges={['top']} style={styles.screen}>
      <FlatList
        contentContainerStyle={styles.list}
        data={shown}
        keyExtractor={(job) => job.id}
        refreshControl={
          <RefreshControl
            refreshing={jobs.isRefetching}
            onRefresh={() => void jobs.refetch()}
            tintColor={colors.accent}
            colors={[colors.accent]}
            progressBackgroundColor={colors.surface}
          />
        }
        ListHeaderComponent={
          <View style={styles.header}>
            <Text variant="title" accessibilityRole="header">
              Library
            </Text>
            <Card style={styles.quota}>
              {me.isError ? (
                <Text variant="muted" style={styles.error}>
                  Can&apos;t reach the API: {me.error.message}
                </Text>
              ) : (
                <>
                  <View style={styles.quotaRow}>
                    <Text style={styles.quotaText} testID="quota">
                      {me.data
                        ? `${me.data.jobs_this_month} of ${me.data.jobs_per_month} transcriptions`
                        : ' '}
                    </Text>
                    <Text variant="muted">Free plan</Text>
                  </View>
                  <ProgressBar
                    fraction={me.data ? me.data.jobs_this_month / me.data.jobs_per_month : 0}
                  />
                </>
              )}
            </Card>
            <View style={styles.filters}>
              {FILTERS.map(({ value, label }) => (
                <Chip
                  key={value}
                  label={label}
                  selected={filter === value}
                  onPress={() => setFilter(value)}
                />
              ))}
            </View>
            {jobs.isError && <Text style={styles.error}>{jobs.error.message}</Text>}
          </View>
        }
        ListEmptyComponent={
          jobs.isSuccess ? (
            <View style={styles.empty}>
              <Text variant="heading">Nothing here yet</Text>
              <Text variant="muted" style={styles.emptyText}>
                Tap the record button to play something, or import a file. Your scores will show up
                here.
              </Text>
            </View>
          ) : null
        }
        renderItem={({ item }) => <JobCard job={item} />}
      />
    </SafeAreaView>
  );
}

function JobCard({ job }: { job: JobSummary }) {
  const status = STATUS[job.status];
  const running = !isFinished(job.status);
  const Icon = job.instrument === 'guitar' ? Guitar : Piano;
  const instrument = job.instrument === 'guitar' ? 'Guitar' : 'Piano';
  return (
    <Link href={{ pathname: '/jobs/[id]', params: { id: job.id } }} asChild>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`${instrument} take, ${formatWhen(job.created_at)}, ${status.label}`}
        style={({ pressed }) => [
          styles.card,
          running && styles.cardRunning,
          pressed && styles.pressed,
        ]}
      >
        <View style={styles.iconTile}>
          <Icon
            color={
              running ? colors.accent : job.status === 'failed' ? colors.dangerText : colors.text
            }
            size={26}
            strokeWidth={1.8}
          />
        </View>
        <View style={styles.cardBody}>
          <Text variant="label">{instrument} take</Text>
          <Text variant="muted">{formatWhen(job.created_at)}</Text>
        </View>
        {running && <ActivityIndicator color={colors.accent} />}
        <Text style={[styles.status, { color: status.color }]}>{status.label}</Text>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  list: { paddingHorizontal: space.xl, paddingBottom: 40, gap: 10 },
  header: { paddingTop: space.xxl, gap: space.lg, marginBottom: space.sm },
  quota: { gap: 10 },
  quotaRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' },
  quotaText: { fontFamily: fonts.bodySemiBold },
  filters: { flexDirection: 'row', gap: space.sm },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    padding: 14,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
  },
  cardRunning: { borderColor: colors.accent },
  pressed: { opacity: 0.7 },
  iconTile: {
    width: 48,
    height: 48,
    borderRadius: 12,
    backgroundColor: colors.raised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cardBody: { flex: 1, gap: 2 },
  status: { fontFamily: fonts.bodySemiBold, fontSize: 13 },
  empty: { alignItems: 'center', gap: space.sm, marginTop: 48, paddingHorizontal: space.lg },
  emptyText: { textAlign: 'center', lineHeight: 20 },
  error: { color: colors.dangerText },
});
