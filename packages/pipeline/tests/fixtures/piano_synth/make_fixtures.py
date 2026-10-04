"""Synthesized piano clips with exact ground truth, for the piano accuracy baseline.

    uv run python packages/pipeline/tests/fixtures/piano_synth/make_fixtures.py

No commercially usable piano dataset with aligned annotations is in the repo (MAESTRO is
CC BY-NC-SA), so these are rendered with the additive piano-like tone from
../basic_pitch/generate_clips.py. Synthetic audio flatters accuracy (TD-8): use the numbers to
catch regressions, not as real-world quality.
"""

import json
import sys
from pathlib import Path

import numpy as np
import soundfile

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))  # the tests dir, as pytest sets it up
from fixtures.basic_pitch.generate_clips import RATE, piano_note, place  # noqa: E402

LEAD_IN_S = 0.5


def render(name: str, bpm: float, notes: list[tuple[float, float, int]], beats: int) -> None:
    """notes: (onset_beat, length_beats, pitch). Each note sounds for 90 % of its length."""
    spb = 60 / bpm
    events, truth_notes = [], []
    for onset_beat, length, pitch in notes:
        onset, sounding = LEAD_IN_S + onset_beat * spb, 0.9 * length * spb
        events.append((onset, piano_note(pitch, sounding)))
        truth_notes.append(
            {"onset_s": round(onset, 4), "offset_s": round(onset + sounding, 4), "pitch": pitch}
        )
    seconds = LEAD_IN_S + (beats + 1) * spb
    soundfile.write(
        HERE / f"{name}.flac",
        place(events, seconds).astype(np.float32),
        RATE,
        subtype="PCM_16",
        format="FLAC",
    )
    truth = {
        "track": name,
        "source": "synthesized by make_fixtures.py",
        "license": "same as this repository",
        "tempo_bpm": bpm,
        "notes": sorted(truth_notes, key=lambda n: (n["onset_s"], n["pitch"])),
        "beats_s": [round(LEAD_IN_S + b * spb, 4) for b in range(beats)],
        "downbeats_s": [round(LEAD_IN_S + b * spb, 4) for b in range(0, beats, 4)],
    }
    (HERE / f"{name}.truth.json").write_text(json.dumps(truth, indent=1) + "\n")
    print(f"{name}: {len(truth_notes)} notes")


def melody_and_chords() -> None:
    melody = [60, 62, 64, 65, 67, 69, 67, 65, 64, 62, 60, 62, 64, 67, 72, 67] * 2
    notes = [(float(i), 1.0, p) for i, p in enumerate(melody)]
    chords = [(48, 52, 55), (53, 57, 60), (55, 59, 62), (48, 52, 55)] * 2
    notes += [(4.0 * bar, 4.0, p) for bar, chord in enumerate(chords) for p in chord]
    render("melody_chords_100bpm", 100, notes, beats=32)


def arpeggios() -> None:
    patterns = [(45, 52, 57, 60), (41, 48, 53, 57), (43, 50, 55, 59), (40, 47, 52, 56)]
    notes = [
        (bar * 4 + step * 0.5, 0.5, pattern[step % 4] + 12 * (step // 4))
        for bar, pattern in enumerate(patterns * 2)
        for step in range(8)
    ]
    render("arpeggios_72bpm", 72, notes, beats=32)


if __name__ == "__main__":
    melody_and_chords()
    arpeggios()
