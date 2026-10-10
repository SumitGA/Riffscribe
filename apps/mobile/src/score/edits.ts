import type { Tuning } from '@/api/client';

/**
 * The editor's operations (ADR-0011), mirroring `pipeline.edits` on the server, which checks
 * and applies them. Notes are addressed by their position in beats (a fraction string, "3/2")
 * and pitch, as the server's score has them.
 */
export type NoteRef = { onset_beats: string; pitch: number };

export type Edit =
  | { op: 'set_position'; note: NoteRef; string: number; fret: number }
  | { op: 'set_pitch'; note: NoteRef; pitch: number; string?: number }
  | { op: 'delete'; note: NoteRef }
  | { op: 'add'; onset_beats: string; duration_beats: string; pitch: number; string?: number }
  | { op: 'set_duration'; note: NoteRef; duration_beats: string };

/** A note the user tapped in the score (the viewer page reports it). */
export type TappedNote = {
  onsetBeats: string;
  durationBeats: string;
  pitch: number;
  /** Tab position, 1 = highest string; null on a notation-only (piano) score. */
  string: number | null;
  fret: number | null;
};

/** Open-string pitches, lowest string first, as the pipeline's TUNINGS. */
const TUNINGS: Record<Tuning, number[]> = {
  standard: [40, 45, 50, 55, 59, 64],
  drop_d: [38, 45, 50, 55, 59, 64],
};
export const MAX_FRET = 24;

/** Every (string, fret) that plays `pitch`, string 1 = highest, with the capo's frets taken off. */
export function positionsFor(
  pitch: number,
  tuning: Tuning = 'standard',
  capo = 0,
): { string: number; fret: number }[] {
  const open = TUNINGS[tuning].map((p) => p + capo).reverse(); // index 0 = string 1
  return open
    .map((openPitch, index) => ({ string: index + 1, fret: pitch - openPitch }))
    .filter(({ fret }) => fret >= 0 && fret <= MAX_FRET - capo);
}

const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** "E4" for MIDI 64. */
export function noteName(pitch: number): string {
  return `${NAMES[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

export function noteKey(note: NoteRef): string {
  return `${note.onset_beats}|${note.pitch}`;
}

/**
 * Pending changes, one per note: a later change to the same note replaces the earlier one, so
 * every operation refers to the note as it is in the saved version (the score on screen).
 */
export function upsertEdit(edits: Edit[], edit: Edit): Edit[] {
  if (edit.op === 'add') {
    return [...edits, edit];
  }
  const key = noteKey(edit.note);
  return [...edits.filter((e) => e.op === 'add' || noteKey(e.note) !== key), edit];
}
