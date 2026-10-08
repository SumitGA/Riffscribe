import { useClerk, useUser } from '@clerk/expo';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useApi } from '@/api/provider';
import { colors, fonts, space } from '@/theme';
import { Button, Card, ProgressBar, Row, Text } from '@/ui';

/** Who's signed in, this month's usage, and sign out. */
export default function Account() {
  const api = useApi();
  const { user } = useUser();
  const { signOut } = useClerk();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });

  const email = user?.primaryEmailAddress?.emailAddress;
  const name = user?.fullName || email || 'Signed in';
  const provider = user?.externalAccounts[0]?.provider;
  const signedInWith = provider
    ? `Signed in with ${provider.charAt(0).toUpperCase()}${provider.slice(1)}`
    : email;

  const onSignOut = async () => {
    await signOut();
    queryClient.clear(); // the next user must not see this one's cached data
  };

  return (
    <SafeAreaView edges={['top']} style={styles.screen}>
      <ScrollView contentContainerStyle={styles.content}>
        <Text variant="title" accessibilityRole="header">
          Account
        </Text>

        <Card style={styles.profile}>
          <View style={styles.avatar}>
            <Text style={styles.initial}>{name.charAt(0).toUpperCase()}</Text>
          </View>
          <View style={styles.profileText}>
            <Text variant="label" testID="account-name">
              {name}
            </Text>
            {signedInWith && <Text variant="muted">{signedInWith}</Text>}
          </View>
        </Card>

        <Card style={styles.plan}>
          <View style={styles.planRow}>
            <Text variant="label">Free plan</Text>
          </View>
          <ProgressBar fraction={me.data ? me.data.jobs_this_month / me.data.jobs_per_month : 0} />
          <Text variant="muted">
            {me.data
              ? `${me.data.jobs_this_month} of ${me.data.jobs_per_month} transcriptions this month · up to 5 min each`
              : ' '}
          </Text>
        </Card>

        <Card style={styles.list}>
          <Row label="Appearance">
            <Text variant="muted">Dark</Text>
          </Row>
          <Row label="Version" last>
            <Text variant="mono">{Constants.expoConfig?.version ?? '–'}</Text>
          </Row>
        </Card>

        <Button title="Sign out" kind="danger" onPress={onSignOut} />
      </ScrollView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.background },
  content: { padding: space.xl, paddingTop: space.xxl, gap: space.lg },
  profile: { flexDirection: 'row', alignItems: 'center', gap: 14 },
  avatar: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  initial: { fontFamily: fonts.display, fontSize: 20, color: colors.onAccent },
  profileText: { flex: 1, gap: 2 },
  plan: { gap: space.md },
  planRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  list: { padding: 0 },
});
