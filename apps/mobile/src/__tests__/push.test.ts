import Constants from 'expo-constants';
import * as Notifications from 'expo-notifications';
import { getItemAsync, setItemAsync } from 'expo-secure-store';

import { askForPushOnce, disablePush, enablePush, jobIdOf, pushState } from '@/push';

const mockStore = new Map<string, string>();
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn(async (key: string) => mockStore.get(key) ?? null),
  setItemAsync: jest.fn(async (key: string, value: string) => void mockStore.set(key, value)),
  deleteItemAsync: jest.fn(async (key: string) => void mockStore.delete(key)),
}));
let mockIsDevice = true;
jest.mock('expo-device', () => ({
  __esModule: true,
  get isDevice() {
    return mockIsDevice;
  },
}));
jest.mock('expo-constants', () => ({ __esModule: true, default: { expoConfig: { extra: {} } } }));
jest.mock('expo-notifications', () => ({
  AndroidImportance: { HIGH: 4 },
  setNotificationChannelAsync: jest.fn(async () => null),
  getPermissionsAsync: jest.fn(),
  requestPermissionsAsync: jest.fn(),
  getExpoPushTokenAsync: jest.fn(async () => ({ data: 'ExponentPushToken[phone]' })),
}));

const api = {
  registerPushToken: jest.fn(async () => {}),
  removePushToken: jest.fn(async () => {}),
};
const permission = (status: string) => ({ status }) as never;

beforeEach(() => {
  mockStore.clear();
  jest.clearAllMocks();
  mockIsDevice = true;
  Constants.expoConfig!.extra = { eas: { projectId: 'project-1' } };
  jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission('undetermined'));
  jest.mocked(Notifications.requestPermissionsAsync).mockResolvedValue(permission('granted'));
});

describe('push', () => {
  it('is unavailable without an Expo project or on an emulator', async () => {
    Constants.expoConfig!.extra = {};
    expect(await pushState()).toBe('unavailable');
    expect(await enablePush(api)).toBe('unavailable');
    Constants.expoConfig!.extra = { eas: { projectId: 'project-1' } };
    mockIsDevice = false;
    expect(await enablePush(api)).toBe('unavailable');
    expect(api.registerPushToken).not.toHaveBeenCalled();
  });

  it('asks, registers the device and remembers its token', async () => {
    expect(await pushState()).toBe('off');
    expect(await enablePush(api)).toBe('on');
    expect(Notifications.getExpoPushTokenAsync).toHaveBeenCalledWith({ projectId: 'project-1' });
    expect(api.registerPushToken).toHaveBeenCalledWith('ExponentPushToken[phone]', 'ios');
    jest.mocked(Notifications.getPermissionsAsync).mockResolvedValue(permission('granted'));
    expect(await pushState()).toBe('on');
  });

  it('respects a refusal', async () => {
    jest.mocked(Notifications.requestPermissionsAsync).mockResolvedValue(permission('denied'));
    expect(await enablePush(api)).toBe('denied');
    expect(api.registerPushToken).not.toHaveBeenCalled();
  });

  it('turns off by unregistering the token', async () => {
    await enablePush(api);
    await disablePush(api);
    expect(api.removePushToken).toHaveBeenCalledWith('ExponentPushToken[phone]');
    expect(await getItemAsync('riffscribe.pushToken')).toBeNull();
  });

  it('offers notifications only once', async () => {
    await askForPushOnce(api);
    await askForPushOnce(api);
    expect(Notifications.requestPermissionsAsync).toHaveBeenCalledTimes(1);
    expect(setItemAsync).toHaveBeenCalledWith('riffscribe.pushAsked', 'yes');
  });

  it('finds the job a notification is about', () => {
    const response = (data: object) =>
      ({ notification: { request: { content: { data } } } }) as never;
    expect(jobIdOf(response({ jobId: 'job-1' }))).toBe('job-1');
    expect(jobIdOf(response({}))).toBeUndefined();
    expect(jobIdOf(null)).toBeUndefined();
  });
});
