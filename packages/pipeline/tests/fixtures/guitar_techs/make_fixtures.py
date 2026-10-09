"""Build the Guitar-TECHS accuracy fixtures: 20 s excerpts plus ground truth (CC BY 4.0).

    uv run python packages/pipeline/tests/fixtures/guitar_techs/make_fixtures.py

Guitar-TECHS (2025) is electric guitar recorded through a miked amp, with per-string MIDI from a
hexaphonic pickup. Unlike GuitarSet, no model we use was trained on it (Basic Pitch trained on
most of GuitarSet, TD-11), so it gives an honest accuracy number. Reads only the needed files
from the Zenodo zips with HTTP range requests. Writes `<clip>.flac` (mono, 44.1 kHz) and
`<clip>.truth.json` (notes with string and fret; no beats or chords) plus ATTRIBUTION.md.
"""

import io
import json
import math
import sys
import zipfile
from pathlib import Path
from typing import Any

import mido
import numpy as np
import soundfile
from scipy.signal import resample_poly, stft

sys.path.insert(0, str(Path(__file__).parents[2]))  # the tests dir
from fixtures.guitarset.make_fixtures import HttpRangeFile

HERE = Path(__file__).parent
ZENODO = "https://zenodo.org/records/14963133/files/"  # Guitar-TECHS
EXCERPT_S = 20.0
LEAD_IN_S = 0.5
RATE = 44_100
STANDARD_TUNING = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}  # string number -> open pitch
# The MIDI is offset from the sound by a few tens of ms, differently per recording (32 ms late on
# one take, 38 ms early on another), so each file's offset is measured, without any
# transcription model: line each MIDI note up with the energy rise at its own pitch.
FLUX_HOP_S = 0.002
MAX_LATENCY_S = 0.15
# (clip name, zip, MIDI member, audio member): four solos by player 3 and four chord recordings
# by players 1 and 2, through the miked amp.
SELECTION = [
    (f"music_{n}", "P3_music", f"midi/midi_{n}.mid", f"audio/micamp/micamp_{n}.wav")
    for n in ("02", "05", "08", "11")
] + [
    (
        f"chords_{player}_{name}",
        f"{player}_chords",
        f"midi/midi_{name}.mid",
        f"audio/micamp/micamp_{name}.wav",
    )
    for player, name in (
        ("P1", "Set1_maj"),
        ("P1", "Set1_7"),
        ("P2", "Set2_min"),
        ("P2", "Set1_m7"),
    )
]


def midi_latency(samples: np.ndarray, rate: int, notes: list[dict[str, Any]]) -> float:
    """How late the MIDI onsets are relative to the audio (seconds; negative = early).

    Each MIDI note is compared with the rise in energy at its own pitch (fundamental and octave),
    so the steady string-to-string spacing of a strum can't line up a note with its neighbour.
    The file's latency is the median of the notes' best lags: a few loud or mistracked notes
    would otherwise dominate a summed score.
    """
    hop = int(rate * FLUX_HOP_S)
    freqs, _, spectrum = stft(
        samples, rate, nperseg=4096, noverlap=4096 - hop, boundary=None, padded=False
    )
    rise = np.maximum(np.diff(np.log1p(100 * np.abs(spectrum)), axis=1), 0)
    times = (np.arange(rise.shape[1]) + 1) * FLUX_HOP_S + 2048 / rate  # STFT frame centres
    lags = np.arange(-int(MAX_LATENCY_S / FLUX_HOP_S), int(MAX_LATENCY_S / FLUX_HOP_S) + 1)
    best_lags = []
    for note in notes:
        f0 = 440.0 * 2 ** ((note["pitch"] - 69) / 12)
        bins = [
            b
            for harmonic in (1, 2)
            for b in np.flatnonzero(np.abs(freqs / (harmonic * f0) - 1) < 0.03)
        ]
        index = int(np.searchsorted(times, note["onset_s"]))
        frames = index + lags
        valid = (frames >= 0) & (frames < times.size)
        if bins and valid.all():
            best_lags.append(lags[int(np.argmax(rise[np.ix_(bins, frames)].sum(axis=0)))])
    # A note's best lag is where the audio rises relative to its MIDI onset; MIDI is late by -lag.
    return float(-np.median(best_lags) * FLUX_HOP_S)


def midi_notes(data: bytes, latency_s: float = 0.0) -> list[dict[str, Any]]:
    """Notes from the per-string MIDI: channel 0 is string 1 (high e), channel 5 string 6."""
    notes, started, now = [], {}, 0.0
    for message in mido.MidiFile(file=io.BytesIO(data)):
        now += message.time
        if message.type == "note_on" and message.velocity > 0:
            started[(message.channel, message.note)] = now
        elif message.type in ("note_on", "note_off"):
            start = started.pop((message.channel, message.note), None)
            if start is not None:
                string = message.channel + 1
                notes.append(
                    {
                        "onset_s": start - latency_s,
                        "offset_s": now - latency_s,
                        "pitch": message.note,
                        "string": string,
                        "fret": message.note - STANDARD_TUNING[string],
                    }
                )
    return sorted(notes, key=lambda n: (n["onset_s"], n["pitch"]))


def main() -> None:
    zips: dict[str, zipfile.ZipFile] = {}
    for clip, archive, midi_member, audio_member in SELECTION:
        if archive not in zips:
            raw = HttpRangeFile(f"{ZENODO}{archive}.zip?download=1")
            zips[archive] = zipfile.ZipFile(io.BufferedReader(raw, 1 << 20))
        z = zips[archive]
        samples, rate = soundfile.read(
            io.BytesIO(z.read(f"{archive}/{audio_member}")), dtype="float32"
        )
        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        midi = z.read(f"{archive}/{midi_member}")
        latency = midi_latency(samples, rate, midi_notes(midi))
        notes = midi_notes(midi, latency)
        start = max(0.0, math.floor((notes[0]["onset_s"] - LEAD_IN_S) * 10) / 10)
        excerpt = samples[int(start * rate) : int((start + EXCERPT_S) * rate)]
        divisor = math.gcd(RATE, rate)
        excerpt = resample_poly(excerpt, RATE // divisor, rate // divisor).astype(np.float32)
        soundfile.write(HERE / f"{clip}.flac", excerpt, RATE, subtype="PCM_16", format="FLAC")

        kept = []
        for n in notes:
            onset = n["onset_s"] - start
            if 0 <= onset < EXCERPT_S and n["fret"] >= 0:
                kept.append(
                    n
                    | {
                        "onset_s": round(onset, 4),
                        "offset_s": round(min(n["offset_s"] - start, EXCERPT_S), 4),
                    }
                )
        truth = {
            "track": clip,
            "source": f"Guitar-TECHS, {archive}/{audio_member}, https://zenodo.org/records/14963133",
            "license": "CC BY 4.0",
            "start_s": start,
            "duration_s": EXCERPT_S,
            "midi_latency_s": round(latency, 3),
            "notes": kept,
        }
        (HERE / f"{clip}.truth.json").write_text(json.dumps(truth, indent=1) + "\n")
        print(f"{clip}: {len(kept)} notes, MIDI latency {latency * 1000:+.0f} ms")


if __name__ == "__main__":
    main()
