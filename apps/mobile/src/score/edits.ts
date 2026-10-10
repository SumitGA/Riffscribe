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

/** An empty spot the user tapped, where a note can be added. */
export type TappedBeat = { onsetBeats: string; durationBeats: string; tab: boolean };

/** Note lengths the editor offers, in beats (a quarter note is one beat). */
export const LENGTHS = [
  { beats: '1/4', label: '1/16' },
  { beats: '1/2', label: '1/8' },
  { beats: '1', label: '1/4' },
  { beats: '2', label: '1/2' },
  { beats: '4', label: 'Whole' },
] as const;

/** Open-string pitches, lowest string first, as the pipeline's TUNINGS. */
const TUNINGS: Record<Tuning, number[]> = {
  standard: [40, 45, 50, 55, 59, 64],
  drop_d: [38, 45, 50, 55, 59, 64],
};
export const MAX_FRET = 24;

/** Sounding open-string pitches with the capo, index 0 = string 1 (highest). */
export function openStrings(tuning: Tuning = 'standard', capo = 0): number[] {
  return TUNINGS[tuning].map((p) => p + capo).reverse();
}

/** Every (string, fret) that plays `pitch`, string 1 = highest, with the capo's frets taken off. */
export function positionsFor(
  pitch: number,
  tuning: Tuning = 'standard',
  capo = 0,
): { string: number; fret: number }[] {
  return openStrings(tuning, capo)
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

/** Whether two beat fractions ("2/2", "1") are equal. */
export function sameBeats(a: string, b: string): boolean {
  const value = (f: string) => {
    const [n, d = '1'] = f.split('/');
    return Number(n) / Number(d);
  };
  return Math.abs(value(a) - value(b)) < 1e-9;
}
