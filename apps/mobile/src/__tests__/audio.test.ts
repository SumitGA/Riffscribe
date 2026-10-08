import { getDocumentAsync } from 'expo-document-picker';

import { formatDuration, formatSize, uploadContentType } from '@/audio/clip';
import { pickAudioFile } from '@/audio/pickAudioFile';

jest.mock('expo-document-picker', () => ({ getDocumentAsync: jest.fn() }));

describe('uploadContentType', () => {
  it('keeps a MIME type the API accepts', () => {
    expect(uploadContentType('take.m4a', 'audio/x-m4a')).toBe('audio/x-m4a');
  });

  it('falls back to the extension when the picker reports something generic', () => {
    expect(uploadContentType('Take 1.MP3', 'application/octet-stream')).toBe('audio/mpeg');
    expect(uploadContentType('riff.wav', undefined)).toBe('audio/wav');
  });

  it('rejects what the API would', () => {
    expect(uploadContentType('song.opus', 'audio/opus')).toBeNull();
    expect(uploadContentType('notes.txt', 'text/plain')).toBeNull();
  });
});

describe('formatting', () => {
  it('formats durations as m:ss', () => {
    expect(formatDuration(0)).toBe('0:00');
    expect(formatDuration(83_400)).toBe('1:23');
    expect(formatDuration(300_000)).toBe('5:00');
  });

  it('formats sizes', () => {
    expect(formatSize(300)).toBe('1 KB');
    expect(formatSize(512 * 1024)).toBe('512 KB');
    expect(formatSize(2.34 * 1024 * 1024)).toBe('2.3 MB');
  });
});

describe('pickAudioFile', () => {
  const picked = (asset: object) =>
    jest.mocked(getDocumentAsync).mockResolvedValue({
      canceled: false,
      assets: [asset],
    } as Awaited<ReturnType<typeof getDocumentAsync>>);

  it('returns a clip for a supported file', async () => {
    picked({ uri: 'file:///cache/riff.mp3', name: 'riff.mp3', mimeType: 'audio/mpeg', size: 42 });
    await expect(pickAudioFile()).resolves.toEqual({
      kind: 'picked',
      clip: {
        uri: 'file:///cache/riff.mp3',
        name: 'riff.mp3',
        contentType: 'audio/mpeg',
        sizeBytes: 42,
      },
    });
  });

  it('says which file is unsupported', async () => {
    picked({ uri: 'file:///cache/a.opus', name: 'a.opus', mimeType: 'audio/opus', size: 1 });
    await expect(pickAudioFile()).resolves.toEqual({ kind: 'unsupported', name: 'a.opus' });
  });

  it('reports a cancel', async () => {
    jest.mocked(getDocumentAsync).mockResolvedValue({ canceled: true, assets: null });
    await expect(pickAudioFile()).resolves.toEqual({ kind: 'canceled' });
  });
});
