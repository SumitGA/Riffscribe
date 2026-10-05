import { Platform } from 'react-native';

/**
 * Where the TabScribe API is. Set EXPO_PUBLIC_API_URL to override; Expo inlines EXPO_PUBLIC_*
 * variables at build time, so it must be read as a literal `process.env.EXPO_PUBLIC_API_URL`.
 *
 * Without it, the app targets a backend on the development machine: the iOS Simulator shares the
 * Mac's network (`localhost`), the Android Emulator reaches the host at 10.0.2.2, and a physical
 * phone needs the Mac's LAN address (`make mobile HOST_IP=...` sets the variable).
 */
export function apiUrl(
  env: string | undefined = process.env.EXPO_PUBLIC_API_URL,
  os: typeof Platform.OS = Platform.OS,
): string {
  if (env) {
    return env.replace(/\/+$/, '');
  }
  return os === 'android' ? 'http://10.0.2.2:8000' : 'http://localhost:8000';
}
