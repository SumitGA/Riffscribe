import { useClerk, useUser } from '@clerk/expo';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Constants from 'expo-constants';
import { Link } from 'expo-router';
import { ChevronRight } from 'lucide-react-native';
import { Alert, Pressable, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { useApi } from '@/api/provider';
import { forgetAllTakes } from '@/audio/takes';
import { disablePush, enablePush, pushState } from '@/push';
import { colors, fonts, space } from '@/theme';
import { Button, Card, ProgressBar, Row, Text, Toggle } from '@/ui';

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

  const push = useQuery({ queryKey: ['push'], queryFn: pushState });
  const setPush = useMutation({
    mutationFn: async (on: boolean) =>
      on ? enablePush(api) : disablePush(api).then(() => 'off' as const),
    onSuccess: (state) => {
      if (state === 'denied') {
        Alert.alert(
          'Notifications are off',
          "Android is blocking notifications for Riffscribe. Turn them on in the phone's Settings > Apps > Riffscribe > Notifications.",
        );
      }
    },
    onError: (error) => Alert.alert("Couldn't turn on notifications", error.message),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['push'] }),
  });

  // Deleting the account (a store requirement): everything on the server, then this phone's
  // copies of the recordings, then sign out. Safe to repeat if Clerk couldn't be reached.
  const deleteAccount = useMutation({
    mutationFn: () => api.deleteAccount(),
    onSuccess: async () => {
      forgetAllTakes();
      await disablePush(api).catch(() => {});
      await signOut();
      queryClient.clear();
    },
    onError: (error) => Alert.alert("Couldn't delete your account", error.message),
  });
  const confirmDelete = () =>
    Alert.alert(
      'Delete your account?',
      'This permanently deletes your account, every transcription and its versions, and the recordings kept on this phone. It can’t be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Delete', style: 'destructive', onPress: () => deleteAccount.mutate() },
      ],
    );

  const onSignOut = async () => {
    // Stop this device's notifications before the account changes hands.
    await disablePush(api).catch(() => {});
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
          {push.data && push.data !== 'unavailable' && (
            <Row label="Notify me when a score is ready">
              {push.data === 'denied' ? (
                <Text variant="muted">Blocked in Settings</Text>
              ) : (
                <Toggle
                  label="Notifications"
                  value={setPush.isPending ? !!setPush.variables : push.data === 'on'}
                  onChange={(on) => setPush.mutate(on)}
                />
              )}
            </Row>
          )}
          <Row label="Appearance">
            <Text variant="muted">Dark</Text>
          </Row>
          <Row label="Version">
            <Text variant="mono">{Constants.expoConfig?.version ?? '–'}</Text>
          </Row>
          <Link href="/acknowledgements" asChild>
            <Pressable accessibilityRole="link">
              <Row label="Acknowledgements" last>
                <ChevronRight color={colors.muted} size={18} />
              </Row>
            </Pressable>
          </Link>
        </Card>

        <Button title="Sign out" kind="secondary" onPress={onSignOut} />
        <Button
          title="Delete account"
          kind="danger"
          loading={deleteAccount.isPending}
          onPress={confirmDelete}
        />
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
