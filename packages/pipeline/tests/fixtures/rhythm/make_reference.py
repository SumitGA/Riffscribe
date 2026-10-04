"""Onset envelopes and librosa 1.0.0 beat-tracking outputs for the parity tests (ADR-0005).

Two steps, in two environments (librosa is deliberately not a project dependency):

1. In this project, write the envelopes:
       uv run python packages/pipeline/tests/fixtures/rhythm/make_reference.py envelopes
2. In a throwaway env with librosa, record its tempo and beats:
       uv venv /tmp/lr --python 3.12 && uv pip install -p /tmp/lr librosa==1.0.0
       /tmp/lr/bin/python packages/pipeline/tests/fixtures/rhythm/make_reference.py reference

Writes `envelopes.npz` (name -> float64 envelope at 22050/256 frames per second) and
`reference.json` (name -> [bpm, [beat frame, ...]]).
"""

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

HERE = Path(__file__).parent
FPS = 22050 / 256


def pulse_train(bpm: float, seconds: float, seed: int) -> np.ndarray:
    """Noise plus one onset per beat, accented every fourth beat."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FPS)
    envelope = rng.uniform(0, 0.2, n)
    period = FPS * 60 / bpm
    for k in range(int(n / period)):
        envelope[int(k * period)] += 1.0 + 0.5 * (k % 4 == 0)
    return envelope


def write_envelopes() -> None:
    import soundfile

    from pipeline.basic_pitch import BasicPitch, onset_envelope

    envelopes: dict[str, Any] = {
        f"pulse{bpm}": pulse_train(bpm, 30, seed=bpm) for bpm in (72, 100, 140, 175)
    }
    model = BasicPitch()
    for clip in ("guitar_like", "piano_like"):
        audio, _ = soundfile.read(HERE.parent / "basic_pitch" / f"{clip}.wav", dtype="float32")
        _, onsets = model.activations(np.tile(audio, 5))  # 30 s
        envelopes[clip] = onset_envelope(onsets, 21, 108).astype(np.float64)
    np.savez_compressed(HERE / "envelopes.npz", **envelopes)
    print(f"wrote {len(envelopes)} envelopes")


def write_reference() -> None:
    import librosa

    envelopes = np.load(HERE / "envelopes.npz")
    reference = {}
    for name in envelopes.files:
        tempo, beats = librosa.beat.beat_track(
            onset_envelope=envelopes[name], sr=22050, hop_length=256
        )
        reference[name] = [float(np.atleast_1d(tempo)[0]), [int(b) for b in beats]]
    (HERE / "reference.json").write_text(json.dumps(reference) + "\n")
    print(f"librosa {librosa.__version__}: {len(reference)} references")


if __name__ == "__main__":
    {"envelopes": write_envelopes, "reference": write_reference}[sys.argv[1]]()
