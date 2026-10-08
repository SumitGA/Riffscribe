/** A piece of audio ready to transcribe: a local file the app recorded or the user picked. */
export type AudioClip = {
  uri: string;
  name: string;
  /** The upload's Content-Type: one the API accepts (see `uploadContentType`). */
  contentType: string;
  sizeBytes: number;
  /** Known for recordings; picked files are measured by the server. */
  durationMs?: number;
  /** Input levels (0-1) sampled while recording, for the review screen's waveform. */
  waveform?: number[];
};

/** The free tier's limit (CLAUDE.md); the server rejects longer audio, this stops sooner. */
export const MAX_RECORDING_MS = 5 * 60 * 1000;

// What the API accepts (services/api AUDIO_TYPES), by file extension. The API stays the judge:
// anything else is rejected there with a message the app shows.
const TYPE_BY_EXTENSION: Record<string, string> = {
  m4a: 'audio/mp4',
  mp4: 'audio/mp4',
  aac: 'audio/aac',
  mp3: 'audio/mpeg',
  wav: 'audio/wav',
  flac: 'audio/flac',
  ogg: 'audio/ogg',
};
const ACCEPTED_TYPES = new Set([
  ...Object.values(TYPE_BY_EXTENSION),
  'audio/x-m4a',
  'audio/x-wav',
  'audio/wave',
]);

/**
 * The Content-Type to upload a file as, or null if it isn't audio the API accepts. Pickers report
 * MIME types unreliably (Android often says `application/octet-stream`), so the extension decides
 * when the reported type isn't one we know.
 */
export function uploadContentType(name: string, mimeType?: string | null): string | null {
  if (mimeType && ACCEPTED_TYPES.has(mimeType)) {
    return mimeType;
  }
  const extension = name.split('.').pop()?.toLowerCase() ?? '';
  return TYPE_BY_EXTENSION[extension] ?? null;
}

/** 83_000 → "1:23". */
export function formatDuration(ms: number): string {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/** 2_400_000 → "2.3 MB". */
export function formatSize(bytes: number): string {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
