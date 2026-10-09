import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  type PressableProps,
  StyleSheet,
  Text as RNText,
  type TextProps,
  View,
  type ViewProps,
} from 'react-native';

import { colors, fonts, radius, space, TOUCH } from '@/theme';

type Variant = 'title' | 'heading' | 'body' | 'label' | 'muted' | 'caption' | 'mono' | 'timer';

/** Text in one of the app's styles. */
export function Text({ variant = 'body', style, ...props }: TextProps & { variant?: Variant }) {
  return <RNText style={[styles.text, textStyles[variant], style]} {...props} />;
}

type ButtonKind = 'primary' | 'secondary' | 'danger';

export function Button({
  title,
  kind = 'primary',
  icon,
  loading,
  style,
  ...props
}: PressableProps & { title: string; kind?: ButtonKind; icon?: ReactNode; loading?: boolean }) {
  const ink =
    kind === 'primary' ? colors.onAccent : kind === 'danger' ? colors.dangerText : colors.text;
  return (
    <Pressable
      accessibilityRole="button"
      style={(state) => [
        styles.button,
        buttonStyles[kind],
        (state.pressed || props.disabled) && styles.dimmed,
        typeof style === 'function' ? style(state) : style,
      ]}
      {...props}
    >
      {loading ? <ActivityIndicator color={ink} /> : icon}
      <RNText style={[styles.buttonText, { color: ink }]}>{title}</RNText>
    </Pressable>
  );
}

/** A round button with only an icon; `label` is what screen readers say. */
export function IconButton({
  label,
  children,
  filled,
  size = TOUCH,
  style,
  ...props
}: PressableProps & { label: string; children: ReactNode; filled?: boolean; size?: number }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      hitSlop={size < TOUCH ? (TOUCH - size) / 2 : undefined}
      style={(state) => [
        styles.iconButton,
        { width: size, height: size, borderRadius: size / 2 },
        filled && styles.iconButtonFilled,
        state.pressed && styles.dimmed,
        typeof style === 'function' ? style(state) : style,
      ]}
      {...props}
    >
      {children}
    </Pressable>
  );
}

export function Card({ style, ...props }: ViewProps) {
  return <View style={[styles.card, style]} {...props} />;
}

/** A small rounded choice, filter or setting. */
export function Chip({
  label,
  selected,
  trailing,
  ...props
}: PressableProps & { label: string; selected?: boolean; trailing?: ReactNode }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ selected }}
      style={({ pressed }) => [
        styles.chip,
        selected && styles.chipSelected,
        pressed && styles.dimmed,
      ]}
      {...props}
    >
      <RNText style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</RNText>
      {trailing}
    </Pressable>
  );
}

/** Two or three mutually exclusive options in one bar. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  label,
  emphasis = 'accent',
}: {
  options: { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  emphasis?: 'accent' | 'subtle';
}) {
  return (
    <View accessibilityRole="radiogroup" accessibilityLabel={label} style={styles.segmented}>
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => onChange(option.value)}
            style={[
              styles.segment,
              selected && (emphasis === 'accent' ? styles.segmentAccent : styles.segmentSubtle),
            ]}
          >
            <RNText
              style={[
                styles.segmentText,
                selected && emphasis === 'accent' && styles.segmentTextAccent,
                selected && styles.segmentTextSelected,
              ]}
            >
              {option.label}
            </RNText>
          </Pressable>
        );
      })}
    </View>
  );
}

/** An on/off switch in the app's style. */
export function Toggle({
  value,
  onChange,
  label,
}: {
  value: boolean;
  onChange: (value: boolean) => void;
  label: string;
}) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityLabel={label}
      accessibilityState={{ checked: value }}
      hitSlop={6}
      onPress={() => onChange(!value)}
      style={[styles.toggle, value ? styles.toggleOn : styles.toggleOff]}
    >
      <View style={[styles.knob, value ? styles.knobOn : styles.knobOff]} />
    </Pressable>
  );
}

/** A thin horizontal bar filled to `fraction` (0-1). */
export function ProgressBar({ fraction, height = 6 }: { fraction: number; height?: number }) {
  const width = `${Math.round(Math.min(1, Math.max(0, fraction)) * 100)}%` as const;
  return (
    <View style={[styles.track, { height, borderRadius: height / 2 }]}>
      <View style={[styles.fill, { width, height, borderRadius: height / 2 }]} />
    </View>
  );
}

/** A row in a settings-style list: label on the left, value or control on the right. */
export function Row({
  label,
  children,
  last,
}: {
  label: string;
  children?: ReactNode;
  last?: boolean;
}) {
  return (
    <View style={[styles.row, !last && styles.rowDivider]}>
      <Text>{label}</Text>
      {children}
    </View>
  );
}

const textStyles = StyleSheet.create({
  title: { fontFamily: fonts.display, fontSize: 32, letterSpacing: -0.5 },
  heading: { fontFamily: fonts.display, fontSize: 18 },
  body: { fontFamily: fonts.body, fontSize: 15 },
  label: { fontFamily: fonts.bodySemiBold, fontSize: 16 },
  muted: { fontFamily: fonts.body, fontSize: 13, color: colors.muted },
  caption: { fontFamily: fonts.body, fontSize: 12, color: colors.muted },
  mono: { fontFamily: fonts.mono, fontSize: 13, color: colors.muted },
  timer: { fontFamily: fonts.monoBold, fontSize: 64, letterSpacing: -2 },
});

const styles = StyleSheet.create({
  text: { color: colors.text },
  dimmed: { opacity: 0.6 },
  button: {
    minHeight: 52,
    borderRadius: radius.lg,
    paddingHorizontal: space.xl,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: space.sm,
  },
  buttonText: { fontFamily: fonts.bodySemiBold, fontSize: 16 },
  iconButton: { alignItems: 'center', justifyContent: 'center' },
  iconButtonFilled: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  card: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.line,
    padding: space.lg,
  },
  chip: {
    minHeight: 36,
    paddingHorizontal: 14,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
  },
  chipSelected: { backgroundColor: colors.text, borderColor: colors.text },
  chipText: { fontFamily: fonts.body, fontSize: 14, color: colors.text },
  chipTextSelected: { color: colors.background, fontFamily: fonts.bodySemiBold },
  segmented: {
    flexDirection: 'row',
    padding: 4,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.line,
  },
  segment: {
    flex: 1,
    minHeight: 40,
    borderRadius: radius.sm,
    alignItems: 'center',
    justifyContent: 'center',
  },
  segmentAccent: { backgroundColor: colors.accent },
  segmentSubtle: { backgroundColor: colors.line },
  segmentText: { fontFamily: fonts.body, fontSize: 15, color: colors.text },
  segmentTextSelected: { fontFamily: fonts.bodySemiBold },
  segmentTextAccent: { color: colors.onAccent },
  toggle: { width: 52, height: 32, borderRadius: 16, padding: 3 },
  toggleOn: { backgroundColor: colors.accent, alignItems: 'flex-end' },
  toggleOff: { backgroundColor: colors.line, alignItems: 'flex-start' },
  knob: { width: 26, height: 26, borderRadius: 13 },
  knobOn: { backgroundColor: colors.onAccent },
  knobOff: { backgroundColor: colors.muted },
  track: { backgroundColor: colors.line, overflow: 'hidden' },
  fill: { backgroundColor: colors.accent },
  row: {
    minHeight: 52,
    paddingHorizontal: space.lg,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: space.md,
  },
  rowDivider: { borderBottomWidth: 1, borderBottomColor: colors.line },
});

const buttonStyles = StyleSheet.create({
  primary: { backgroundColor: colors.accent },
  secondary: { borderWidth: 1, borderColor: colors.line },
  danger: { borderWidth: 1, borderColor: colors.line },
});
