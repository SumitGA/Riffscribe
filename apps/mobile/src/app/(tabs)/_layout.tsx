import { router, Tabs } from 'expo-router';
import { ListMusic, Mic, UserRound } from 'lucide-react-native';
import type { ComponentProps } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { usePushResponses } from '@/push/usePushResponses';
import { colors, fonts } from '@/theme';
import { Text } from '@/ui';

/** Library and Account, with the record button raised between them (it opens New take). */
export default function TabsLayout() {
  usePushResponses();
  return (
    <Tabs screenOptions={{ headerShown: false }} tabBar={(props) => <TabBar {...props} />}>
      <Tabs.Screen name="index" options={{ title: 'Library' }} />
      <Tabs.Screen name="account" options={{ title: 'Account' }} />
    </Tabs>
  );
}

// expo-router doesn't export the tab bar's props type; take it from the Tabs component.
type TabBarProps = Parameters<NonNullable<ComponentProps<typeof Tabs>['tabBar']>>[0];

const ICONS = { index: ListMusic, account: UserRound } as const;

function TabBar({ state, navigation, descriptors }: TabBarProps) {
  const insets = useSafeAreaInsets();
  const tab = (index: number) => {
    const route = state.routes[index];
    if (!route) {
      return null;
    }
    const focused = state.index === index;
    const Icon = ICONS[route.name as keyof typeof ICONS];
    const color = focused ? colors.accent : colors.muted;
    return (
      <Pressable
        key={route.key}
        accessibilityRole="tab"
        accessibilityState={{ selected: focused }}
        onPress={() => !focused && navigation.navigate(route.name)}
        style={styles.tab}
      >
        <Icon color={color} size={24} strokeWidth={2} />
        <Text style={[styles.tabLabel, { color }, focused && styles.tabLabelFocused]}>
          {descriptors[route.key]?.options.title}
        </Text>
      </Pressable>
    );
  };

  return (
    <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 12) }]}>
      {tab(0)}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Record a new take"
        onPress={() => router.push('/new')}
        style={({ pressed }) => [styles.record, pressed && styles.pressed]}
      >
        <Mic color={colors.onAccent} size={30} strokeWidth={2.2} />
      </Pressable>
      {tab(1)}
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 28,
    paddingTop: 10,
    backgroundColor: colors.tabBar,
    borderTopWidth: 1,
    borderTopColor: colors.line,
  },
  tab: { width: 72, minHeight: 48, alignItems: 'center', justifyContent: 'center', gap: 4 },
  tabLabel: { fontSize: 12 },
  tabLabelFocused: { fontFamily: fonts.bodySemiBold },
  record: {
    width: 68,
    height: 68,
    borderRadius: 34,
    marginTop: -34,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 6,
    borderColor: colors.background,
  },
  pressed: { opacity: 0.8 },
});
