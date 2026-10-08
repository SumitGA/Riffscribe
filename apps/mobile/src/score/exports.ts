import { File, Directory, Paths } from 'expo-file-system';
import { printToFileAsync } from 'expo-print';
import { shareAsync } from 'expo-sharing';

import type { PresignedRequest } from '@/api/client';

export type ExportFormat = 'musicxml' | 'midi' | 'guitarPro' | 'pdf';

/** How each format is offered and saved; `uti` is the type iOS's share sheet uses. */
export const FORMATS: Record<
  ExportFormat,
  { label: string; detail: string; extension: string; mimeType: string; uti: string }
> = {
  pdf: {
    label: 'PDF',
    detail: 'Printable sheet music',
    extension: 'pdf',
    mimeType: 'application/pdf',
    uti: 'com.adobe.pdf',
  },
  guitarPro: {
    label: 'Guitar Pro',
    detail: 'Guitar Pro 7 and other tab apps',
    extension: 'gp',
    mimeType: 'application/octet-stream',
    uti: 'public.data',
  },
  musicxml: {
    label: 'MusicXML',
    detail: 'MuseScore, Sibelius, Finale, Dorico',
    extension: 'musicxml',
    mimeType: 'application/vnd.recordare.musicxml+xml',
    uti: 'public.xml',
  },
  midi: {
    label: 'MIDI',
    detail: 'GarageBand, Logic, Ableton and other DAWs',
    extension: 'mid',
    mimeType: 'audio/midi',
    uti: 'public.midi-audio',
  },
};

/** "Blues riff: take #2!" → "Blues riff take 2.mid"; empty titles fall back to the app's name. */
export function fileName(title: string, format: ExportFormat): string {
  const base = title
    .replace(/[^\p{L}\p{N} _.-]+/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 80);
  return `${base || 'Riffscribe score'}.${FORMATS[format].extension}`;
}

/** A fresh file in the app's export folder (cache: the OS may clear it). */
function exportFile(name: string): File {
  const folder = new Directory(Paths.cache, 'exports');
  folder.create({ idempotent: true });
  const file = new File(folder, name);
  if (file.exists) {
    file.delete();
  }
  return file;
}

function share(file: File, format: ExportFormat) {
  const { mimeType, uti, label } = FORMATS[format];
  return shareAsync(file.uri, { mimeType, UTI: uti, dialogTitle: `Share ${label}` });
}

/** Downloads one of the job's files (a presigned GET) and opens the share sheet. */
export async function shareDownload(request: PresignedRequest, name: string, format: ExportFormat) {
  const file = await File.downloadFileAsync(request.url, exportFile(name), {
    headers: request.headers,
  });
  await share(file, format);
}

/** Saves base64 data (from the score page) and opens the share sheet. */
export async function shareBase64(data: string, name: string, format: ExportFormat) {
  const file = exportFile(name);
  file.write(Uint8Array.from(atob(data), (c) => c.charCodeAt(0)));
  await share(file, format);
}

/** Prints an HTML page to an A4 PDF and opens the share sheet. */
export async function sharePdf(html: string, name: string) {
  const { uri } = await printToFileAsync({ html, width: 595, height: 842 });
  const file = exportFile(name);
  await new File(uri).move(file);
  await share(file, 'pdf');
}
