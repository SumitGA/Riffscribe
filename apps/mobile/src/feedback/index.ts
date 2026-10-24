import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { Platform } from 'react-native';

/** Where feedback goes: the contact address in the privacy policy (infra/site/privacy.html). */
export const FEEDBACK_EMAIL = 'sumitga.playstore@gmail.com';

export type DeviceInfo = { version: string; os: string; model: string };

export function deviceInfo(): DeviceInfo {
  return {
    version: Constants.expoConfig?.version ?? 'unknown',
    os: `${Platform.OS === 'ios' ? 'iOS' : 'Android'} ${Device.osVersion ?? Platform.Version}`,
    model: Device.modelName ?? 'unknown',
  };
}

/** A mailto: link with the app version and phone filled in, so replies can reproduce problems. */
export function feedbackMailto(info: DeviceInfo): string {
  const subject = 'Riffscribe feedback';
  const body = [
    '',
    '',
    '---',
    `App version: ${info.version}`,
    `Phone: ${info.model} (${info.os})`,
  ].join('\n');
  return `mailto:${FEEDBACK_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
}
