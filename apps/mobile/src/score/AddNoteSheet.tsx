import { Minus, Plus } from 'lucide-react-native';
import { useState } from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Tuning } from '@/api/client';
import { colors, radius, space } from '@/theme';
import { Button, Chip, IconButton, Text } from '@/ui';

import { type Edit, LENGTHS, MAX_FRET, noteName, openStrings, type TappedBeat } from './edits';

/** Add a missed note where the user tapped: on guitar by string and fret, else by pitch. */
export function AddNoteSheet({
  beat,
  tuning,
  capo,
  onEdit,
  onClose,
}: {
  beat: TappedBeat;
  tuning: Tuning;
  capo: number;
  onEdit: (edit: Edit) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const [string, setString] = useState(1);
  const [fret, setFret] = useState(0);
  const [pitch, setPitch] = useState(60);
  const [length, setLength] = useState<string>(
    LENGTHS.find((l) => l.beats === beat.durationBeats)?.beats ?? '1',
  );
  const notePitch = beat.tab ? openStrings(tuning, capo)[string - 1]! + fret : pitch;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header">
          Add a note · {noteName(notePitch)}
        </Text>

        {beat.tab ? (
          <>
            <View style={styles.section}>
              <Text variant="muted">String</Text>
              <View style={styles.chips}>
                {[1, 2, 3, 4, 5, 6].map((s) => (
                  <Chip
                    key={s}
                    label={String(s)}
                    selected={s === string}
                    onPress={() => setString(s)}
                  />
                ))}
              </View>
            </View>
            <Stepper
              label="Fret"
              value={String(fret)}
              onDown={() => setFret((f) => Math.max(0, f - 1))}
              onUp={() => setFret((f) => Math.min(MAX_FRET - capo, f + 1))}
            />
          </>
        ) : (
          <Stepper
            label="Note"
            value={noteName(pitch)}
            onDown={() => setPitch((p) => Math.max(21, p - 1))}
            onUp={() => setPitch((p) => Math.min(108, p + 1))}
          />
        )}

        <View style={styles.section}>
          <Text variant="muted">Length</Text>
          <View style={styles.chips}>
            {LENGTHS.map(({ beats, label }) => (
              <Chip
                key={beats}
                label={label}
                selected={beats === length}
                onPress={() => setLength(beats)}
              />
            ))}
          </View>
        </View>

        <Button
          title="Add note"
          onPress={() => {
            onEdit({
              op: 'add',
              onset_beats: beat.onsetBeats,
              duration_beats: length,
              pitch: notePitch,
              ...(beat.tab ? { string } : {}),
            });
            onClose();
          }}
        />
      </View>
    </Modal>
  );
}

function Stepper({
  label,
  value,
  onDown,
  onUp,
}: {
  label: string;
  value: string;
  onDown: () => void;
  onUp: () => void;
}) {
  return (
    <View style={styles.section}>
      <Text variant="muted">{label}</Text>
      <View style={styles.stepper}>
        <IconButton label={`${label} down`} onPress={onDown}>
          <Minus color={colors.text} size={22} />
        </IconButton>
        <Text style={styles.value}>{value}</Text>
        <IconButton label={`${label} up`} onPress={onUp}>
          <Plus color={colors.text} size={22} />
        </IconButton>
      </View>
    </View>
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
    paddingHorizontal: space.xl,
    gap: space.lg,
  },
  section: { gap: space.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  stepper: { flexDirection: 'row', alignItems: 'center', gap: space.lg },
  value: { fontSize: 18, minWidth: 48, textAlign: 'center' },
});
