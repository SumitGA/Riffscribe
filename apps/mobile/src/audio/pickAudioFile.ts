import { getDocumentAsync } from 'expo-document-picker';

import { type AudioClip, uploadContentType } from './clip';

export type PickResult =
  | { kind: 'picked'; clip: AudioClip }
  | { kind: 'canceled' }
  | { kind: 'unsupported'; name: string };

/** Lets the user choose an audio file; it's copied into the app's cache, so its URI is readable. */
export async function pickAudioFile(): Promise<PickResult> {
  const result = await getDocumentAsync({ type: 'audio/*', copyToCacheDirectory: true });
  const asset = result.canceled ? undefined : result.assets[0];
  if (!asset) {
    return { kind: 'canceled' };
  }
  const contentType = uploadContentType(asset.name, asset.mimeType);
  if (!contentType) {
    return { kind: 'unsupported', name: asset.name };
  }
  return {
    kind: 'picked',
    clip: { uri: asset.uri, name: asset.name, contentType, sizeBytes: asset.size ?? 0 },
  };
}
