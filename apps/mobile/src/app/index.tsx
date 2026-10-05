import { StyleSheet, Text, View } from 'react-native';

import { apiUrl } from '@/config';

// Placeholder home screen; recording, jobs and the score viewer replace it in later commits.
export default function Home() {
  return (
    <View style={styles.container}>
      <Text style={styles.title}>TabScribe</Text>
      <Text style={styles.subtitle}>Audio to sheet music and guitar tab</Text>
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
