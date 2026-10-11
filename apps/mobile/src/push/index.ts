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
/** Set when the user switches notifications off in Account; sign-in then leaves them off. */
const OFF_KEY = 'riffscribe.pushOff';
/** How long to wait for Google's / Apple's push service to hand out a token. */
export const TOKEN_TIMEOUT_MS = 20_000;
/** Android groups notifications in channels; the worker sends to this one. */
const CHANNEL = 'default';

export type PushState = 'on' | 'off' | 'denied' | 'unavailable';

/**
 * The Expo project the app's push tokens belong to (`npx eas-cli@latest init` writes it to app.json). Without
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
  const token = await pushToken(id);
  await api.registerPushToken(token, Platform.OS === 'ios' ? 'ios' : 'android');
  await setItemAsync(TOKEN_KEY, token);
  await deleteItemAsync(OFF_KEY);
  return 'on';
}

/**
 * The device's Expo push token. Getting it asks Google's (or Apple's) push service, which can
 * fail to answer at all; without a time limit the switch would look "on" while nothing happens.
 */
async function pushToken(projectId: string): Promise<string> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<never>((_, reject) => {
    timer = setTimeout(
      () =>
        reject(
          new Error(
            "The phone's notification service didn't answer. Check the connection (and on Android, that Google Play services is up to date), then try again.",
          ),
        ),
      TOKEN_TIMEOUT_MS,
    );
  });
  try {
    const { data } = await Promise.race([
      Notifications.getExpoPushTokenAsync({ projectId }),
      timeout,
    ]);
    return data;
  } finally {
    clearTimeout(timer);
  }
}

/** The user switched notifications off in Account: unregister, and stay off after sign-in. */
export async function turnOffPush(api: Pick<Api, 'removePushToken'>): Promise<void> {
  await setItemAsync(OFF_KEY, 'yes');
  await disablePush(api);
}

/**
 * After sign-in and on every app start: if the phone allows notifications and the user hasn't
 * switched them off, register this device for whoever is signed in now. Signing out (or
 * deleting the account) unregisters it, so without this the next sign-in would be silent. It
 * also refreshes a token the push service has replaced. Never asks for permission; never throws.
 */
export async function syncPush(api: Pick<Api, 'registerPushToken'>): Promise<void> {
  try {
    if (!pushAvailable() || (await getItemAsync(OFF_KEY))) {
      return;
    }
    const { status } = await Notifications.getPermissionsAsync();
    if (status === 'granted') {
      await enablePush(api);
    }
  } catch (error) {
    console.warn('push registration failed', error);
  }
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
  } catch (error) {
    // Registration failed (network, Expo, Firebase); the Account screen can try again and shows
    // the error there.
    console.warn('push registration failed', error);
  }
}
