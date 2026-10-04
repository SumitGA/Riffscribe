"""Grid-search Basic Pitch decoding settings for guitar on the tuning set; judge on held-out clips.

    uv run python packages/pipeline/tests/tuning/make_tuning_set.py   # once
    uv run python packages/pipeline/tests/tuning/tune_decoding.py

The model runs once per clip (activations are cached); each settings combination only re-runs
note decoding (Rust, milliseconds). Settings are ranked on the tuning clips only; the committed
test clips (tests/fixtures/guitarset) are scored at the end as an unbiased check.
"""

import itertools
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import mir_eval
import numpy as np
import soundfile
from scipy.signal import resample_poly

sys.path.insert(0, str(Path(__file__).parents[1]))  # the tests dir
from accuracy_eval import _hz, _intervals
from tuning.make_tuning_set import CACHE

from pipeline.basic_pitch import BasicPitch, DecodeParams, decode_notes, level_gain
from pipeline.config import Instrument, PipelineConfig
from pipeline.runner import run_pipeline
from pipeline.stages.normalize import NormalizedAudio, NormalizeStage
from pipeline.stages.transcribe import PITCH_RANGE

TEST_DIR = Path(__file__).parents[1] / "fixtures" / "guitarset"
LOW, HIGH = PITCH_RANGE[Instrument.GUITAR]
# Second pass: the first grid (onset 0.3-0.7, frame 0.2-0.5, min frames 6/11/16) peaked at its
# edges (frame 0.5, min frames 6), so this one extends past them around that peak.
GRID: dict[str, list[Any]] = {
    "onset_threshold": [0.5, 0.55, 0.6, 0.65],
    "frame_threshold": [0.45, 0.5, 0.55, 0.6, 0.65],
    "min_note_frames": [3, 4, 6, 8],  # ~35, 46, 70, 93 ms
    "infer_onsets": [True, False],
    "melodia_trick": [True, False],
    "level_normalize": [False, True],
}
DEFAULTS: dict[str, Any] = {
    "onset_threshold": 0.5,
    "frame_threshold": 0.3,
    "min_note_frames": 11,
    "infer_onsets": True,
    "melodia_trick": True,
    "level_normalize": False,
}


def load(directory: Path, model: BasicPitch) -> list[dict[str, Any]]:
    """Clips with model activations computed through the real normalize path (cached)."""
    clips = []
    for truth_path in sorted(directory.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text())
        cached = CACHE / "activations" / f"{truth['track']}.npz"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory() as work:
                cfg = PipelineConfig(instrument=Instrument.GUITAR)
                audio_path = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
                result = run_pipeline(audio_path, Path(work), cfg, [NormalizeStage()])
                normalized = result.output(NormalizedAudio)
                audio, _ = soundfile.read(Path(work) / normalized.audio.path, dtype="float32")
            frames, onsets = model.activations(resample_poly(audio, 1, 2).astype(np.float32))
            np.savez_compressed(cached, frames=frames, onsets=onsets, shift=normalized.trim_start_s)
        data = np.load(cached)
        clips.append(
            {
                "truth": truth,
                "frames": data["frames"],
                "onsets": data["onsets"],
                "shift": float(data["shift"]),
            }
        )
    return clips


def score(clip: dict[str, Any], settings: dict[str, Any]) -> tuple[float, float, float]:
    settings = dict(settings)
    normalize = settings.pop("level_normalize", False)
    gain = level_gain(clip["frames"], LOW, HIGH) if normalize else 1.0
    params = DecodeParams(min_pitch=LOW, max_pitch=HIGH, **settings)
    notes = decode_notes(clip["frames"] * gain, clip["onsets"] * gain, params)
    ref = clip["truth"]["notes"]
    precision, recall, f1, _ = mir_eval.transcription.precision_recall_f1_overlap(
        _intervals([(n["onset_s"], n["offset_s"]) for n in ref]),
        _hz([n["pitch"] for n in ref]),
        _intervals([(n.start_s + clip["shift"], n.end_s + clip["shift"]) for n in notes]),
        _hz([n.pitch for n in notes]),
        offset_ratio=None,
    )
    return precision, recall, f1


def mean_scores(clips: list[dict[str, Any]], settings: dict[str, Any]) -> Any:
    return np.mean([score(c, settings) for c in clips], axis=0)


def main() -> None:
    model = BasicPitch()
    tuning, test = load(CACHE, model), load(TEST_DIR, model)
    print(f"tuning clips: {len(tuning)} | held-out test clips: {len(test)}")
    results = []
    for values in itertools.product(*GRID.values()):
        settings = dict(zip(GRID, values, strict=True))
        results.append((mean_scores(tuning, settings), settings))
    results.sort(key=lambda r: -float(r[0][2]))

    print("\nTop settings on the TUNING clips (precision, recall, F1):")
    for (p, r, f), s in results[:8]:
        print(f"  P {p:.3f} R {r:.3f} F1 {f:.3f}  {s}")
    print("\nOn the HELD-OUT test clips:")
    for label, settings in (("defaults", DEFAULTS), ("best on tuning", results[0][1])):
        p, r, f = mean_scores(test, settings)
        tf = mean_scores(tuning, settings)[2]
        print(f"  {label:15s} test P {p:.3f} R {r:.3f} F1 {f:.3f} | tuning F1 {tf:.3f}")
    best_normalized = next(s for _, s in results if s["level_normalize"])
    p, r, f = mean_scores(test, best_normalized)
    print(f"  {'best normalized':15s} test P {p:.3f} R {r:.3f} F1 {f:.3f} | {best_normalized}")
    print("\nbest:", json.dumps(results[0][1]))


if __name__ == "__main__":
    main()
