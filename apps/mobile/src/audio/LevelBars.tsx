import { StyleSheet, View } from 'react-native';

import { colors } from '@/theme';

/** The recorder's metering (dBFS, about -60 to 0) as a 0-1 bar height; silence is a sliver. */
export function levelFromDecibels(db: number | undefined): number {
  if (db === undefined || !Number.isFinite(db)) {
    return 0.05;
  }
  return Math.min(1, Math.max(0.05, (db + 60) / 60));
}

/** `levels` resampled to `count` bars by taking the loudest sample in each slice. */
export function resample(levels: number[], count: number): number[] {
  if (levels.length <= count) {
    return levels;
  }
  return Array.from({ length: count }, (_, i) => {
    const slice = levels.slice(
      Math.floor((i * levels.length) / count),
      Math.floor(((i + 1) * levels.length) / count),
    );
    return Math.max(...slice);
  });
}

/**
 * Vertical bars for audio levels (0-1). With `progress`, bars before it are accent-coloured and
 * the rest dimmed (a playhead); without, recorded bars are accent and empty slots grey.
 */
export function LevelBars({
  levels,
  count,
  height,
  progress,
}: {
  levels: number[];
  count: number;
  height: number;
  progress?: number;
}) {
  const bars = resample(levels, count);
  const played = progress === undefined ? bars.length : Math.round(progress * bars.length);
  return (
    <View
      accessible={false}
      importantForAccessibility="no-hide-descendants"
      style={[styles.row, { height }]}
    >
      {Array.from({ length: progress === undefined ? count : bars.length }, (_, i) => {
        const level = bars[i];
        return (
          <View
            key={i}
            style={[
              styles.bar,
              {
                height: Math.max(4, (level ?? 0.05) * height),
                backgroundColor:
                  level === undefined ? colors.line : i < played ? colors.accent : colors.faint,
              },
            ]}
          />
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 3,
    alignSelf: 'stretch',
  },
  bar: { flex: 1, maxWidth: 4, borderRadius: 2 },
});
