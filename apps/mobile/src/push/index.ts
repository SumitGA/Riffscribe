import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import { deleteItemAsync, getItemAsync, setItemAsync } from 'expo-secure-store';
import { Platform } from 'react-native';

import type { Api } from '@/api/client';

/** Where this install's push token is kept, so sign-out can unregister it. */
const TOKEN_KEY = 'riffscribe.pushToken';
/** Set once the app has asked for notification permission, so it doesn't keep asking. */
const ASKED_KEY = 'riffscribe.pushAsked';
/** Android groups notifications in channels; the worker sends to this one. */
const CHANNEL = 'default';

export type PushState = 'on' | 'off' | 'denied' | 'unavailable';

/**
 * The Expo project the app's push tokens belong to (`eas init` writes it to app.json). Without
 * one, or on an emulator, push isn't available and the app simply doesn't offer it.
 */
function projectId(): string | undefined {
  const extra = Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined;
  return extra?.eas?.projectId ?? Constants.easConfig?.projectId;
}

export function pushAvailable(): boolean {
  return Device.isDevice && projectId() !== undefined;
}

/** What the Account screen shows: on (registered), off, denied by the OS, or unavailable. */
export async function pushState(): Promise<PushState> {
  if (!pushAvailable()) {
    return 'unavailable';
  }
  const { status } = await Notifications.getPermissionsAsync();
  if (status === 'denied') {
    return 'denied';
  }
  return (await getItemAsync(TOKEN_KEY)) ? 'on' : 'off';
}

/**
 * Asks for permission if needed, then registers this device with the API so the worker can
 * notify it. Returns what happened; never throws for "no" or "not available".
 */
export async function enablePush(api: Pick<Api, 'registerPushToken'>): Promise<PushState> {
  const id = projectId();
  if (!Device.isDevice || !id) {
    return 'unavailable';
  }
  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(CHANNEL, {
      name: 'Scores ready',
      importance: Notifications.AndroidImportance.HIGH,
    });
  }
  let { status } = await Notifications.getPermissionsAsync();
  if (status !== 'granted') {
    ({ status } = await Notifications.requestPermissionsAsync());
  }
  if (status !== 'granted') {
    return 'denied';
  }
  const { data: token } = await Notifications.getExpoPushTokenAsync({ projectId: id });
  await api.registerPushToken(token, Platform.OS === 'ios' ? 'ios' : 'android');
  await setItemAsync(TOKEN_KEY, token);
  return 'on';
}

/** Stops notifications to this device (turned off, or signing out). Best effort. */
export async function disablePush(api: Pick<Api, 'removePushToken'>): Promise<void> {
  const token = await getItemAsync(TOKEN_KEY);
  if (!token) {
    return;
  }
  try {
    await api.removePushToken(token);
  } finally {
    await deleteItemAsync(TOKEN_KEY);
  }
}

/** The job a notification is about (the worker sends `{ jobId }`). */
export function jobIdOf(response: Notifications.NotificationResponse | null | undefined) {
  const data = response?.notification.request.content.data as { jobId?: unknown } | undefined;
  return typeof data?.jobId === 'string' ? data.jobId : undefined;
}

/**
 * The first time the user sends a transcription, offer notifications. Later changes go through
 * the Account screen. Never throws: a failure here mustn't spoil the transcription.
 */
export async function askForPushOnce(api: Pick<Api, 'registerPushToken'>): Promise<void> {
  try {
    if (!pushAvailable() || (await getItemAsync(ASKED_KEY))) {
      return;
    }
    await setItemAsync(ASKED_KEY, 'yes');
    await enablePush(api);
  } catch {
    // Registration failed (network, Expo); the Account screen can try again.
  }
}
