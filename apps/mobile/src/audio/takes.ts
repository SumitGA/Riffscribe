import { Directory, File, Paths } from 'expo-file-system';

/**
 * The app's own copy of each take it sent, kept on this phone so the score can play the real
 * recording in step with the notation. The server keeps no audio for this (ADR-0009): another
 * phone, or this one after a reinstall, plays the synthesized guitar instead.
 *
 * Files live in the app's documents (not the cache, which the system may clear), named
 * `<job id>.<extension>`, and are removed when the job is deleted.
 */
const folder = () => new Directory(Paths.document, 'takes');

/** Copies the recorded or picked file for `jobId`. Never rejects: playback is a bonus. */
export async function keepTake(jobId: string, uri: string): Promise<void> {
  try {
    const source = new File(uri);
    const extension = source.extension || '.m4a';
    folder().create({ idempotent: true, intermediates: true });
    await source.copy(new File(folder(), `${jobId}${extension}`));
  } catch (error) {
    console.warn(`couldn't keep the take for job ${jobId}`, error);
  }
}

/** This phone's copy of the take for `jobId`, if it has one. */
export function findTake(jobId: string): File | null {
  const dir = folder();
  if (!dir.exists) {
    return null;
  }
  const take = dir
    .list()
    .find((entry): entry is File => entry instanceof File && entry.name.startsWith(`${jobId}.`));
  return take ?? null;
}

/** Removes this phone's copy of the take for `jobId`, if any. */
export function forgetTake(jobId: string): void {
  try {
    findTake(jobId)?.delete();
  } catch (error) {
    console.warn(`couldn't remove the take for job ${jobId}`, error);
  }
}
