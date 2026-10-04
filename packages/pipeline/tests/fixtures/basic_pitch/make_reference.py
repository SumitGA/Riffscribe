"""Record upstream Basic Pitch 0.4.0 outputs for the parity tests (TD-11).

Runs in a throwaway env with the real package, NOT in this project's env, e.g.:
    uv venv /tmp/bp-ref --python 3.12
    uv pip install -p /tmp/bp-ref onnxruntime librosa resampy mir_eval pretty_midi scipy numpy
    uv pip install -p /tmp/bp-ref basic-pitch==0.4.0 --no-deps  # skips its TensorFlow pin
    /tmp/bp-ref/bin/python packages/pipeline/tests/fixtures/basic_pitch/make_reference.py

Recorded with onnxruntime 1.30.0, numpy 2.5.3, librosa 1.0.0.

Writes, per clip: `<clip>.activations.npz` (model note/onset activations) and
`<clip>.notes.json` (note events with default thresholds, no frequency limits).
"""

import json
from pathlib import Path

import numpy as np
from basic_pitch import inference

HERE = Path(__file__).parent
MODEL = Path(inference.__file__).parent / "saved_models" / "icassp_2022" / "nmp.onnx"

if __name__ == "__main__":
    model = inference.Model(MODEL)
    for wav in sorted(HERE.glob("*.wav")):
        out = inference.run_inference(wav, model)
        np.savez_compressed(
            HERE / f"{wav.stem}.activations.npz", note=out["note"], onset=out["onset"]
        )
        _, _, events = inference.predict(wav, model)
        notes = [
            {"start_s": float(s), "end_s": float(e), "pitch": int(p), "amplitude": float(a)}
            for s, e, p, a, _ in sorted(events, key=lambda n: (n[0], n[2]))
        ]
        (HERE / f"{wav.stem}.notes.json").write_text(json.dumps(notes, indent=1) + "\n")
        print(f"{wav.name}: {len(notes)} notes")
