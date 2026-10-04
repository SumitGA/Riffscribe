"""Minimal MIDI writing: one track of notes at a fixed tempo."""

from collections.abc import Sequence
from pathlib import Path

import mido

TICKS_PER_BEAT = 480
TEMPO_BPM = 120  # placeholder grid; real tempo comes from the quantize stage
_TICKS_PER_SECOND = TICKS_PER_BEAT * TEMPO_BPM / 60


def write_notes(
    path: Path, notes: Sequence[tuple[float, float, int, int]], program: int = 0
) -> None:
    """Write (onset_s, offset_s, pitch, velocity) notes as a single-track MIDI file."""
    events: list[tuple[int, int, mido.Message]] = []
    for onset, offset, pitch, velocity in notes:
        on, off = _ticks(onset), max(_ticks(offset), _ticks(onset) + 1)
        # At equal ticks, note-offs (0) sort before note-ons (1) so repeated notes don't merge.
        events.append((on, 1, mido.Message("note_on", note=pitch, velocity=velocity)))
        events.append((off, 0, mido.Message("note_off", note=pitch, velocity=0)))
    events.sort(key=lambda e: (e[0], e[1], e[2].note))

    track = mido.MidiTrack()
    track.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(TEMPO_BPM), time=0))
    track.append(mido.Message("program_change", program=program, time=0))
    previous = 0
    for tick, _, message in events:
        track.append(message.copy(time=tick - previous))
        previous = tick
    track.append(mido.MetaMessage("end_of_track", time=0))

    midi = mido.MidiFile(ticks_per_beat=TICKS_PER_BEAT)
    midi.tracks.append(track)
    midi.save(path)


def _ticks(seconds: float) -> int:
    return max(0, round(seconds * _TICKS_PER_SECOND))
