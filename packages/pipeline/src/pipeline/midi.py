"""Minimal MIDI writing: one track of notes at one tempo."""

from collections.abc import Sequence
from pathlib import Path

import mido

TICKS_PER_BEAT = 480
DEFAULT_TEMPO_BPM = 120.0  # placeholder grid before the quantize stage knows the tempo


def write_notes(
    path: Path,
    notes: Sequence[tuple[float, float, int, int]],
    program: int = 0,
    tempo_bpm: float = DEFAULT_TEMPO_BPM,
) -> None:
    """Write (onset_s, offset_s, pitch, velocity) notes as a single-track MIDI file."""
    ticks_per_second = TICKS_PER_BEAT * tempo_bpm / 60

    def ticks(seconds: float) -> int:
        return max(0, round(seconds * ticks_per_second))

    events: list[tuple[int, int, mido.Message]] = []
    for onset, offset, pitch, velocity in notes:
        on, off = ticks(onset), max(ticks(offset), ticks(onset) + 1)
        # At equal ticks, note-offs (0) sort before note-ons (1) so repeated notes don't merge.
        events.append((on, 1, mido.Message("note_on", note=pitch, velocity=velocity)))
        events.append((off, 0, mido.Message("note_off", note=pitch, velocity=0)))
    events.sort(key=lambda e: (e[0], e[1], e[2].note))

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(tempo_bpm), time=0))
    track.append(mido.Message("program_change", program=program, time=0))
    previous = 0
    for tick, _, message in events:
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))

    midi = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    midi.tracks.append(track)
    midi.save(path)
