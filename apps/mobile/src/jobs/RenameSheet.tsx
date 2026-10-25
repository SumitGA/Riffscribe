import { useState } from 'react';
import {
  KeyboardAvoidingView,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, fonts, radius, space } from '@/theme';
import { Button, Text } from '@/ui';

/** Rename a transcription; a blank name goes back to the default title ("Guitar take"). */
export function RenameSheet({
  name,
  placeholder,
  onSave,
  onClose,
  busy,
  error,
}: {
  name: string;
  placeholder: string;
  onSave: (name: string) => void;
  onClose: () => void;
  busy?: boolean;
  error?: string | null;
}) {
  const insets = useSafeAreaInsets();
  const [value, setValue] = useState(name);
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
        <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
          <Text variant="heading" accessibilityRole="header">
            Rename
          </Text>
          <TextInput
            accessibilityLabel="Name"
            value={value}
            onChangeText={setValue}
            placeholder={placeholder}
            placeholderTextColor={colors.faint}
            maxLength={120}
            autoFocus
            selectTextOnFocus
            returnKeyType="done"
            onSubmitEditing={() => onSave(value)}
            style={styles.input}
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <Button title="Save" loading={busy} disabled={busy} onPress={() => onSave(value)} />
        </View>
      </KeyboardAvoidingView>
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
  input: {
    height: 52,
    paddingHorizontal: space.lg,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.raised,
    color: colors.text,
    fontFamily: fonts.body,
    fontSize: 16,
  },
  error: { color: colors.dangerText },
});
