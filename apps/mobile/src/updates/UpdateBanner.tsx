import * as Updates from 'expo-updates';
import { useEffect } from 'react';
import { AppState, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, space } from '@/theme';
import { Text } from '@/ui';

/**
 * Over-the-air updates (EAS Update) without closing the app: check when it opens and whenever
 * it comes back to the foreground, download in the background, then offer a one-tap restart.
 * Development builds have updates disabled, so this renders nothing there.
 */
export function UpdateBanner() {
  const insets = useSafeAreaInsets();
  const { isUpdateAvailable, isUpdatePending } = Updates.useUpdates();

  useEffect(() => {
    if (!Updates.isEnabled) {
      return;
    }
    const check = () => {
      Updates.checkForUpdateAsync().catch(() => {}); // offline: try again next time
    };
    check();
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        check();
      }
    });
    return () => subscription.remove();
  }, []);

  useEffect(() => {
    if (Updates.isEnabled && isUpdateAvailable && !isUpdatePending) {
      Updates.fetchUpdateAsync().catch(() => {});
    }
  }, [isUpdateAvailable, isUpdatePending]);

  if (!Updates.isEnabled || !isUpdatePending) {
    return null;
  }
  return (
    <View style={[styles.wrap, { bottom: insets.bottom + 72 }]} pointerEvents="box-none">
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="A new version of Riffscribe is ready. Restart to use it."
        onPress={() => void Updates.reloadAsync()}
        style={({ pressed }) => [styles.banner, pressed && styles.pressed]}
      >
        <Text style={styles.text}>A new version is ready</Text>
        <Text style={styles.action}>Restart</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: 'absolute', left: space.lg, right: space.lg, alignItems: 'center' },
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: space.lg,
    paddingVertical: space.md,
    paddingHorizontal: space.lg,
    borderRadius: radius.lg,
    backgroundColor: colors.raised,
    borderWidth: 1,
    borderColor: colors.accent,
  },
  pressed: { opacity: 0.7 },
  text: { color: colors.text },
  action: { color: colors.accent },
});
