import { ClerkProvider, useAuth } from '@clerk/expo';
import { tokenCache } from '@clerk/expo/token-cache';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';

import { ApiProvider } from '@/api/provider';
import { clerkPublishableKey } from '@/config';

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient());
  // tokenCache keeps the Clerk session in the device's secure storage (Keychain / Keystore).
  return (
    <ClerkProvider publishableKey={clerkPublishableKey()} tokenCache={tokenCache}>
      <QueryClientProvider client={queryClient}>
        <ApiProvider>
          <Screens />
        </ApiProvider>
      </QueryClientProvider>
      <StatusBar style="auto" />
    </ClerkProvider>
  );
}

// Signed out, the sign-in screen is the only route; signed in, it's unreachable.
function Screens() {
  const { isLoaded, isSignedIn } = useAuth();
  if (!isLoaded) {
    return null; // the splash screen stays up until Clerk has read the stored session
  }
  return (
    <Stack screenOptions={{ headerTitle: 'Riffscribe' }}>
      <Stack.Protected guard={!!isSignedIn}>
        <Stack.Screen name="index" />
        <Stack.Screen name="new" options={{ headerTitle: 'New transcription' }} />
        <Stack.Screen name="jobs/[id]" options={{ headerTitle: 'Transcription' }} />
      </Stack.Protected>
      <Stack.Protected guard={!isSignedIn}>
        <Stack.Screen name="sign-in" options={{ headerShown: false }} />
      </Stack.Protected>
    </Stack>
  );
}
