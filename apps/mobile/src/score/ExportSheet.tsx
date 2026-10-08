import { FileMusic, FileText, Music, Piano } from 'lucide-react-native';
import { useState } from 'react';
import { ActivityIndicator, Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, space } from '@/theme';
import { Text } from '@/ui';

import { type ExportFormat, FORMATS } from './exports';

const ICONS = { pdf: FileText, guitarPro: Music, musicxml: FileMusic, midi: Piano } as const;

/** Export choices; each runs `onExport` (which opens the share sheet) and shows its progress. */
export function ExportSheet({
  visible,
  formats,
  onExport,
  onClose,
}: {
  visible: boolean;
  formats: ExportFormat[];
  onExport: (format: ExportFormat) => Promise<void>;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [busy, setBusy] = useState<ExportFormat | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async (format: ExportFormat) => {
    setBusy(format);
    setError(null);
    try {
      await onExport(format);
      onClose();
    } catch (e) {
      setError(
        `Couldn't export ${FORMATS[format].label}: ${e instanceof Error ? e.message : String(e)}`,
      );
    } finally {
      setBusy(null);
    }
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable
        accessibilityLabel="Close"
        style={styles.backdrop}
        onPress={busy ? undefined : onClose}
      />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header" style={styles.title}>
          Export
        </Text>
        {formats.map((format) => {
          const { label, detail } = FORMATS[format];
          const Icon = ICONS[format];
          return (
            <Pressable
              key={format}
              accessibilityRole="button"
              accessibilityLabel={`${label}: ${detail}`}
              disabled={busy !== null}
              onPress={() => void run(format)}
              style={({ pressed }) => [styles.option, pressed && styles.pressed]}
            >
              <View style={styles.icon}>
                <Icon color={colors.accent} size={22} />
              </View>
              <View style={styles.text}>
                <Text variant="label">{label}</Text>
                <Text variant="muted">{detail}</Text>
              </View>
              {busy === format && <ActivityIndicator color={colors.accent} />}
            </Pressable>
          );
        })}
        {error && <Text style={styles.error}>{error}</Text>}
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
  },
  title: { paddingHorizontal: space.md, marginBottom: space.sm },
  option: {
    minHeight: 64,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  pressed: { backgroundColor: colors.raised },
  icon: {
    width: 40,
    height: 40,
    borderRadius: 10,
    backgroundColor: colors.raised,
    alignItems: 'center',
    justifyContent: 'center',
  },
  text: { flex: 1, gap: 2 },
  error: { color: colors.dangerText, padding: space.md },
});
