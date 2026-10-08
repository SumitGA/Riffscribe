import { Check } from 'lucide-react-native';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, fonts, radius, space } from '@/theme';

import { Text } from './index';

/** A bottom sheet listing choices; picking one closes it. */
export function OptionSheet<T extends string | number>({
  visible,
  title,
  options,
  value,
  onChange,
  onClose,
}: {
  visible: boolean;
  title: string;
  options: { value: T; label: string; detail?: string }[];
  value: T;
  onChange: (value: T) => void;
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose}>
      <Pressable accessibilityLabel="Close" style={styles.backdrop} onPress={onClose} />
      <View style={[styles.sheet, { paddingBottom: insets.bottom + space.lg }]}>
        <Text variant="heading" accessibilityRole="header" style={styles.title}>
          {title}
        </Text>
        {options.map((option) => {
          const selected = option.value === value;
          return (
            <Pressable
              key={String(option.value)}
              accessibilityRole="radio"
              accessibilityState={{ selected }}
              onPress={() => {
                onChange(option.value);
                onClose();
              }}
              style={({ pressed }) => [styles.option, pressed && styles.pressed]}
            >
              <View style={styles.optionText}>
                <Text style={selected && styles.selected}>{option.label}</Text>
                {option.detail && <Text variant="muted">{option.detail}</Text>}
              </View>
              {selected && <Check color={colors.accent} size={20} />}
            </Pressable>
          );
        })}
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
    maxHeight: '70%',
  },
  title: { paddingHorizontal: space.md, marginBottom: space.sm },
  option: {
    minHeight: 52,
    paddingHorizontal: space.md,
    borderRadius: radius.md,
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.md,
  },
  optionText: { flex: 1, gap: 2 },
  selected: { fontFamily: fonts.bodySemiBold, color: colors.accent },
  pressed: { backgroundColor: colors.raised },
});
