import { useQuery } from '@tanstack/react-query';
import { ActivityIndicator, Alert, Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useApi } from '@/api/provider';
import { formatWhen } from '@/jobs/status';
import { colors, radius, space } from '@/theme';
import { Text } from '@/ui';

/**
 * A transcription's versions, newest first (ADR-0011). Restoring an older one saves its content
 * as a new version, so nothing is ever lost.
 */
export function VersionsSheet({
  jobId,
  current,
  onRestore,
  onClose,
}: {
  jobId: string;
  current: number;
  onRestore: (version: number) => void;
  onClose: () => void;
}) {
  const api = useApi();
  const insets = useSafeAreaInsets();
  const versions = useQuery({
    queryKey: ['versions', jobId],
    queryFn: () => api.listVersions(jobId),
  });

  const confirm = (version: number) =>
    Alert.alert(
      `Restore version ${version}?`,
      `Its notes become a new version, after ${current}. Nothing is deleted.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Restore',
          onPress: () => {
            onRestore(version);
            onClose();
          },
        },
      ],
    );

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header" style={styles.title}>
          Versions
        </Text>
        {versions.isPending ? (
          <ActivityIndicator color={colors.accent} />
        ) : versions.isError ? (
          <Text style={styles.error}>{versions.error.message}</Text>
        ) : (
          versions.data.versions.map((v) => {
            const restorable = v.status === 'ready' && v.version !== current;
            return (
              <Pressable
                key={v.version}
                accessibilityRole="button"
                disabled={!restorable}
                onPress={() => confirm(v.version)}
                style={({ pressed }) => [styles.row, pressed && styles.pressed]}
              >
                <View style={styles.text}>
                  <Text>
                    {v.version === 0 ? 'Original transcription' : `Version ${v.version}`}
                    {v.version === current ? ' · showing' : ''}
                  </Text>
                  <Text variant="muted">
                    {formatWhen(v.created_at)}
                    {v.status === 'pending' ? ' · saving…' : ''}
                    {v.status === 'failed' ? ` · not saved: ${v.error_message ?? ''}` : ''}
                  </Text>
                </View>
                {restorable && <Text style={styles.action}>Restore</Text>}
              </Pressable>
            );
          })
        )}
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: 'rgba(0, 0, 0, 0.6)' },
  sheet: {
    backgroundColor: colors.surface,
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    borderTopWidth: 1,
    borderColor: colors.line,
    paddingTop: space.xl,
    paddingHorizontal: space.sm,
    gap: 2,
    maxHeight: '70%',
  },
  title: { paddingHorizontal: space.md, marginBottom: space.sm },
  row: {
    minHeight: 60,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  pressed: { backgroundColor: colors.raised },
  text: { flex: 1, gap: 2 },
  action: { color: colors.accent },
  error: { color: colors.dangerText, padding: space.md },
});
