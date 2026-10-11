import { Check } from 'lucide-react-native';
import { useState } from 'react';
import { Linking, Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, space } from '@/theme';
import { Button, Text } from '@/ui';

import { legalUrl } from './links';

/**
 * Before the first upload (and after the terms change): the user confirms they may use what they
 * upload and that transcriptions are for personal use (ADR-0009). The server records it.
 */
export function TermsSheet({
  onAgree,
  onClose,
  busy,
  error,
}: {
  onAgree: () => void;
  onClose: () => void;
  busy?: boolean;
  error?: string | null;
}) {
  const insets = useSafeAreaInsets();
  const [checked, setChecked] = useState(false);
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header">
          Before your first transcription
        </Text>
        <View style={styles.points}>
          <Text>• Only upload recordings you made or have the right to use.</Text>
          <Text>• Transcriptions are for your personal use. They’re private to you.</Text>
          <Text>• Your audio is deleted from our servers once it’s transcribed.</Text>
        </View>
        <Pressable
          accessibilityRole="checkbox"
          accessibilityState={{ checked }}
          accessibilityLabel="I agree to the Terms of Use and Privacy Policy"
          onPress={() => setChecked((c) => !c)}
          style={styles.agree}
        >
          <View style={[styles.box, checked && styles.boxChecked]}>
            {checked && <Check color={colors.onAccent} size={16} />}
          </View>
          <Text style={styles.agreeText}>
            I agree to the{' '}
            <Text style={styles.link} onPress={() => void Linking.openURL(legalUrl('terms'))}>
              Terms of Use
            </Text>{' '}
            and{' '}
            <Text style={styles.link} onPress={() => void Linking.openURL(legalUrl('privacy'))}>
              Privacy Policy
            </Text>
          </Text>
        </Pressable>
        {error && <Text style={styles.error}>{error}</Text>}
        <Button
          title="Agree and transcribe"
          disabled={!checked || busy}
          loading={busy}
          onPress={onAgree}
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
  points: { gap: space.sm },
  agree: { flexDirection: 'row', alignItems: 'center', gap: space.md },
  box: {
    width: 24,
    height: 24,
    borderRadius: radius.sm / 2,
    borderWidth: 2,
    borderColor: colors.muted,
    alignItems: 'center',
    justifyContent: 'center',
  },
  boxChecked: { backgroundColor: colors.accent, borderColor: colors.accent },
  agreeText: { flex: 1 },
  link: { color: colors.accent, textDecorationLine: 'underline' },
  error: { color: colors.dangerText },
});
