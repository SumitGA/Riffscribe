import { ClerkProvider, useAuth } from '@clerk/expo';
import { tokenCache } from '@clerk/expo/token-cache';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, Stack, ThemeProvider } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { useState } from 'react';

import { ApiProvider } from '@/api/provider';
import { UpdateBanner } from '@/updates/UpdateBanner';
import { clerkPublishableKey } from '@/config';
import { colors, fonts } from '@/theme';
import { useAppFonts } from '@/theme/useAppFonts';

const navigationTheme = {
  ...DarkTheme,
  colors: {
    ...DarkTheme.colors,
    primary: colors.accent,
    background: colors.background,
    card: colors.background,
    text: colors.text,
    border: colors.line,
  },
};

export default function RootLayout() {
  const [queryClient] = useState(() => new QueryClient());
  // tokenCache keeps the Clerk session in the device's secure storage (Keychain / Keystore).
  return (
    <ClerkProvider publishableKey={clerkPublishableKey()} tokenCache={tokenCache}>
      <QueryClientProvider client={queryClient}>
        <ApiProvider>
          <ThemeProvider value={navigationTheme}>
            <Screens />
            <UpdateBanner />
          </ThemeProvider>
        </ApiProvider>
      </QueryClientProvider>
      <StatusBar style="light" />
    </ClerkProvider>
  );
}

// Signed out, the sign-in screen is the only route; signed in, it's unreachable.
function Screens() {
  const { isLoaded, isSignedIn } = useAuth();
  const fontsReady = useAppFonts();
  if (!isLoaded || !fontsReady) {
    return null; // the splash screen stays up until the session and fonts are ready
  }
  return (
    <Stack
      screenOptions={{
        headerStyle: { backgroundColor: colors.background },
        headerTintColor: colors.text,
        headerTitleStyle: { fontFamily: fonts.display, fontSize: 18 },
        headerTitleAlign: 'center',
        headerShadowVisible: false,
        headerBackButtonDisplayMode: 'minimal',
        contentStyle: { backgroundColor: colors.background },
      }}
    >
      <Stack.Protected guard={!!isSignedIn}>
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen
          name="new"
          options={{ headerTitle: 'New take', presentation: 'fullScreenModal' }}
        />
        <Stack.Screen name="jobs/[id]" options={{ headerTitle: '' }} />
      </Stack.Protected>
      <Stack.Protected guard={!isSignedIn}>
        <Stack.Screen name="sign-in" options={{ headerShown: false }} />
      </Stack.Protected>
    </Stack>
  );
}
