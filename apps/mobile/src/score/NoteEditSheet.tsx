import { Minus, Plus } from 'lucide-react-native';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import type { Tuning } from '@/api/client';
import { colors, radius, space } from '@/theme';
import { Button, Chip, IconButton, Text } from '@/ui';

import {
  type Edit,
  LENGTHS,
  noteName,
  type NoteRef,
  positionsFor,
  sameBeats,
  type TappedNote,
} from './edits';

/**
 * What can be changed about a tapped note (ADR-0011): which string plays it, its pitch, or
 * removing it. Each choice is one edit; the screen collects them until Save.
 */
export function NoteEditSheet({
  note,
  tuning,
  capo,
  onEdit,
  onClose,
}: {
  note: TappedNote;
  tuning: Tuning;
  capo: number;
  onEdit: (edit: Edit) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  const ref: NoteRef = { onset_beats: note.onsetBeats, pitch: note.pitch };
  const isTab = note.string !== null;
  const positions = isTab ? positionsFor(note.pitch, tuning, capo) : [];
  const done = (edit: Edit) => {
    onEdit(edit);
    onClose();
  };
  const shiftPitch = (by: number) => {
    const pitch = note.pitch + by;
    // Stay on the same string when it can play the new note; else the server picks one.
    const stays = isTab && positionsFor(pitch, tuning, capo).some((p) => p.string === note.string);
    done({ op: 'set_pitch', note: ref, pitch, ...(stays ? { string: note.string! } : {}) });
  };

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header">
          {noteName(note.pitch)}
          {isTab ? `  ·  string ${note.string}, fret ${note.fret}` : ''}
        </Text>

        {isTab && (
          <View style={styles.section}>
            <Text variant="muted">Play it on</Text>
            <View style={styles.chips}>
              {positions.map(({ string, fret }) => (
                <Chip
                  key={string}
                  label={`String ${string} · fret ${fret}`}
                  selected={string === note.string}
                  onPress={() =>
                    string !== note.string && done({ op: 'set_position', note: ref, string, fret })
                  }
                />
              ))}
            </View>
          </View>
        )}

        <View style={styles.section}>
          <Text variant="muted">Wrong note?</Text>
          <View style={styles.pitchRow}>
            <IconButton label="One semitone down" onPress={() => shiftPitch(-1)}>
              <Minus color={colors.text} size={22} />
            </IconButton>
            <Text style={styles.pitchName}>{noteName(note.pitch)}</Text>
            <IconButton label="One semitone up" onPress={() => shiftPitch(1)}>
              <Plus color={colors.text} size={22} />
            </IconButton>
          </View>
        </View>

        <View style={styles.section}>
          <Text variant="muted">Length</Text>
          <View style={styles.chips}>
            {LENGTHS.map(({ beats, label }) => (
              <Chip
                key={beats}
                label={label}
                selected={sameBeats(beats, note.durationBeats)}
                onPress={() =>
                  !sameBeats(beats, note.durationBeats) &&
                  done({ op: 'set_duration', note: ref, duration_beats: beats })
                }
              />
            ))}
          </View>
        </View>

        <Button
          title="Delete this note"
          kind="danger"
          onPress={() => done({ op: 'delete', note: ref })}
        />
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
    paddingHorizontal: space.xl,
    gap: space.lg,
  },
  section: { gap: space.sm },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: space.sm },
  pitchRow: { flexDirection: 'row', alignItems: 'center', gap: space.lg },
  pitchName: { fontSize: 18, minWidth: 48, textAlign: 'center' },
});
