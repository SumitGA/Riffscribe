import { useClerk, useUser } from '@clerk/expo';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, StyleSheet, Text, View } from 'react-native';

import { useApi } from '@/api/provider';
import { apiUrl } from '@/config';

// Placeholder home screen; recording, jobs and the score viewer replace it in later commits.
// It already calls the API, which shows that sign-in reaches the backend.
export default function Home() {
  const api = useApi();
  const { user } = useUser();
  const { signOut } = useClerk();
  const queryClient = useQueryClient();
  const me = useQuery({ queryKey: ['me'], queryFn: api.me });

  const onSignOut = async () => {
    await signOut();
    queryClient.clear(); // the next user must not see this one's cached data
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Riffscribe</Text>
      <Text style={styles.subtitle}>Audio to sheet music and guitar tab</Text>
      <Text testID="account">{user?.primaryEmailAddress?.emailAddress}</Text>
      <Text testID="quota">
        {me.isPending
          ? 'Checking your quota…'
          : me.isError
            ? `Can't reach the API: ${me.error.message}`
            : `${me.data.jobs_this_month} of ${me.data.jobs_per_month} transcriptions used this month`}
      </Text>
      <Button title="Sign out" onPress={onSignOut} />
      <Text style={styles.detail} testID="api-url">
        API: {apiUrl()}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  title: { fontSize: 28, fontWeight: '600' },
  subtitle: { fontSize: 16, opacity: 0.7 },
  detail: { fontSize: 12, opacity: 0.5, marginTop: 24 },
});
