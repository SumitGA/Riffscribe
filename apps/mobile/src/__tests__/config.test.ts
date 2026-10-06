import { apiUrl, clerkPublishableKey } from '@/config';

describe('apiUrl', () => {
  it('uses EXPO_PUBLIC_API_URL when set, without a trailing slash', () => {
    expect(apiUrl('http://192.168.1.20:8000/', 'ios')).toBe('http://192.168.1.20:8000');
  });

  it('defaults to localhost on the iOS Simulator', () => {
    expect(apiUrl(undefined, 'ios')).toBe('http://localhost:8000');
  });

  it('defaults to the host alias on the Android Emulator', () => {
    expect(apiUrl(undefined, 'android')).toBe('http://10.0.2.2:8000');
  });
});

describe('clerkPublishableKey', () => {
  it('returns the key', () => {
    expect(clerkPublishableKey('pk_test_abc')).toBe('pk_test_abc');
  });

  it('explains how to set it when missing', () => {
    expect(() => clerkPublishableKey('')).toThrow(/\.env\.example/);
  });
});
