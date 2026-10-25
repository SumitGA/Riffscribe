import { router } from 'expo-router';
import { FileMusic, Mic, Play } from 'lucide-react-native';
import { type ComponentType, useRef, useState } from 'react';
import {
  type NativeScrollEvent,
  type NativeSyntheticEvent,
  Pressable,
  ScrollView,
  StyleSheet,
  useWindowDimensions,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, space, TOUCH } from '@/theme';
import { Button, Text } from '@/ui';
import { markWelcomeSeen } from '@/welcome/seen';

type Page = {
  icon: ComponentType<{ color: string; size: number }>;
  title: string;
  body: string;
};

const PAGES: Page[] = [
  {
    icon: Mic,
    title: 'Record or upload',
    body: 'Play a riff into your phone, or pick a recording. Solo guitar or piano, up to 5 minutes.',
  },
  {
    icon: FileMusic,
    title: 'Get tab and sheet music',
    body: 'Riffscribe writes out the notes and chords, usually within a minute or two. Turn on notifications and we’ll tell you when it’s ready.',
  },
  {
    icon: Play,
    title: 'Play, fix and export',
    body: 'Play it back alongside your recording, tap a note to fix it, and export PDF, Guitar Pro, MusicXML or MIDI.',
  },
];

/** A short guide on first launch (and from Account): three pages, skippable. */
export default function Welcome() {
  const { width } = useWindowDimensions();
  // Insets from the hook, not SafeAreaView: in a full-screen modal on iOS the view measured no
  // top inset, which put Skip under the status bar.
  const insets = useSafeAreaInsets();
  const scroller = useRef<ScrollView>(null);
  const [page, setPage] = useState(0);
  const last = page === PAGES.length - 1;

  const done = () => {
    markWelcomeSeen();
    if (router.canGoBack()) {
      router.back();
    } else {
      router.replace('/');
    }
  };
  const next = () => {
    if (last) {
      done();
      return;
    }
    scroller.current?.scrollTo({ x: width * (page + 1), animated: true });
    setPage(page + 1);
  };
  const onScrolled = (event: NativeSyntheticEvent<NativeScrollEvent>) =>
    setPage(Math.round(event.nativeEvent.contentOffset.x / width));

  return (
    <View style={[styles.screen, { paddingTop: insets.top, paddingBottom: insets.bottom }]}>
      <View style={styles.top}>
        {!last && (
          <Pressable accessibilityRole="button" onPress={done} hitSlop={12} style={styles.skip}>
            <Text variant="muted">Skip</Text>
          </Pressable>
        )}
      </View>
      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={onScrolled}
        testID="welcome-pages"
      >
        {PAGES.map(({ icon: Icon, title, body }) => (
          <View key={title} style={[styles.page, { width }]}>
            <View style={styles.badge}>
              <Icon color={colors.accent} size={44} />
            </View>
            <Text variant="title" accessibilityRole="header" style={styles.center}>
              {title}
            </Text>
            <Text style={[styles.center, styles.body]}>{body}</Text>
          </View>
        ))}
      </ScrollView>
      <View style={styles.bottom}>
        <View style={styles.dots} accessibilityLabel={`Page ${page + 1} of ${PAGES.length}`}>
          {PAGES.map(({ title }, i) => (
            <View key={title} style={[styles.dot, i === page && styles.dotActive]} />
          ))}
        </View>
        <Button title={last ? 'Get started' : 'Next'} onPress={next} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  top: {
    height: TOUCH,
    alignItems: 'flex-end',
    justifyContent: 'center',
    paddingHorizontal: space.xl,
  },
  skip: { paddingVertical: space.sm },
  page: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: space.xxl,
    gap: space.lg,
  },
  badge: {
    width: 96,
    height: 96,
    borderRadius: radius.pill,
    backgroundColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: space.md,
  },
  center: { textAlign: 'center' },
  body: { color: colors.muted, fontSize: 16, lineHeight: 24 },
  bottom: { padding: space.xl, gap: space.xl },
  dots: { flexDirection: 'row', justifyContent: 'center', gap: space.sm },
  dot: { width: 8, height: 8, borderRadius: 4, backgroundColor: colors.faint },
  dotActive: { width: 24, backgroundColor: colors.accent },
});
