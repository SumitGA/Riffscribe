import { useState } from 'react';
import { FlatList, Pressable, StyleSheet, View } from 'react-native';

import { assets, type Notice, packages, texts } from '@/about/licenses';
import { colors, radius, space } from '@/theme';
import { Text } from '@/ui';

const ITEMS: (Notice | { header: string })[] = [
  { header: 'Sounds, fonts and models' },
  ...assets,
  { header: `Open-source packages (${packages.length})` },
  ...packages,
];

/** Third-party notices (TD-28): tap an entry to read its licence. */
export default function Acknowledgements() {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <FlatList
      style={styles.screen}
      contentContainerStyle={styles.content}
      data={ITEMS}
      keyExtractor={(item) => ('header' in item ? `#${item.header}` : item.name)}
      ListHeaderComponent={
        <Text variant="muted" style={styles.intro}>
          Riffscribe is built on the work of these projects. Thank you.
        </Text>
      }
      renderItem={({ item }) =>
        'header' in item ? (
          <Text variant="label" accessibilityRole="header" style={styles.header}>
            {item.header}
          </Text>
        ) : (
          <Entry
            notice={item}
            expanded={open === item.name}
            onPress={() => setOpen(open === item.name ? null : item.name)}
          />
        )
      }
    />
  );
}

function Entry({
  notice,
  expanded,
  onPress,
}: {
  notice: Notice;
  expanded: boolean;
  onPress: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityState={{ expanded }}
      onPress={onPress}
      style={styles.entry}
    >
      <View style={styles.entryHead}>
        <Text style={styles.name}>{notice.name}</Text>
        <Text variant="mono">{notice.license}</Text>
      </View>
      {expanded && (
        <View style={styles.body}>
          {notice.copyright.map((line) => (
            <Text key={line} variant="caption">
              {line}
            </Text>
          ))}
          <Text variant="caption" style={styles.licence}>
            {notice.text === null ? 'Licence text not included.' : texts[notice.text]}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: space.xl, gap: space.sm },
  intro: { marginBottom: space.md },
  header: { marginTop: space.lg },
  entry: {
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    padding: space.md,
    gap: space.sm,
  },
  entryHead: { flexDirection: 'row', justifyContent: 'space-between', gap: space.md },
  name: { flexShrink: 1 },
  body: { gap: space.xs },
  licence: { marginTop: space.sm },
});
