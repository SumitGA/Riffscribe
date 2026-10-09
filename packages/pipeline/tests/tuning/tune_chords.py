"""Grid-search chord recognition settings on the tuning set's comp clips; judge on held-out clips.

    uv run python packages/pipeline/tests/tuning/make_tuning_set.py --count 48   # once
    uv run python packages/pipeline/tests/tuning/tune_chords.py

The pipeline runs once per clip up to quantize (cached), so each settings combination only
re-runs chord recognition. Settings are ranked on the tuning clips by major/minor accuracy;
the committed test clips (tests/fixtures/guitarset) are scored at the end as an unbiased check.
"""

import dataclasses
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))  # the tests dir
from accuracy_eval import chord_accuracy
from tuning.make_tuning_set import CACHE

from pipeline.basic_pitch import frame_times
from pipeline.chords import DEFAULT, ChordParams, recognize_chords
from pipeline.config import Instrument, PipelineConfig
from pipeline.runner import run_pipeline
from pipeline.score import HARTE_ROOTS, Score
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import QuantizedScore
from pipeline.stages.transcribe import NoteEvents

TEST_DIR = Path(__file__).parents[1] / "fixtures" / "guitarset"
WORK = CACHE / "chord-work"
# Second pass: the first grid (power 0.5-2, bass weight 0-0.4, stay 0.5-0.95, 1 or 2 spans per
# beat, bass up to 47/52/57) peaked at its edges (power 2, weight 0.4, 2 spans), so this one
# extends past them.
GRID: dict[str, list[Any]] = {
    "qualities": [("maj", "min", "7"), ("maj", "min", "7", "maj7", "min7")],
    "subdivisions": [2, 4],
    "bass_max_pitch": [52, 57],
    "power": [2.0, 3.0, 4.0],
    "bass_weight": [0.3, 0.4, 0.6, 0.8],
    "stay_probability": [0.9, 0.95, 0.98],
}


def load(directory: Path) -> list[dict[str, Any]]:
    """Comp clips with frames, beats and the trim shift, from a cached pipeline run."""
    stages = default_stages()[:4]  # normalize, separate, transcribe, quantize
    clips = []
    for truth_path in sorted(directory.glob("*_comp.truth.json")):
        truth = json.loads(truth_path.read_text())
        audio = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
        work = WORK / truth["track"]
        result = run_pipeline(audio, work, PipelineConfig(instrument=Instrument.GUITAR), stages)
        frames = np.load(work / result.output(NoteEvents).frames.path).astype(np.float64)
        score = Score.model_validate_json(
            (work / result.output(QuantizedScore).score.path).read_text()
        )
        clips.append(
            {
                "truth": truth["chords"],
                "frames": frames,
                "times": frame_times(len(frames)),
                "beats": score.beat_times_s,
                "shift": result.output(NormalizedAudio).trim_start_s,
            }
        )
    return clips


def score(clip: dict[str, Any], params: ChordParams) -> tuple[float, float]:
    beats = recognize_chords(clip["frames"], clip["times"], clip["beats"], params)
    shift = clip["shift"]
    estimated = [
        (c.start_s + shift, c.end_s + shift, f"{HARTE_ROOTS[c.root]}:{c.quality}")
        for beat in beats
        for c in beat
        if c is not None
    ]
    result = chord_accuracy(clip["truth"], estimated)
    return result["chord_majmin"], result["chord_root"]


def mean_scores(clips: list[dict[str, Any]], params: ChordParams) -> Any:
    return np.mean([score(c, params) for c in clips], axis=0)


def main() -> None:
    tuning, test = load(CACHE), load(TEST_DIR)
    print(f"tuning comp clips: {len(tuning)} | held-out test comp clips: {len(test)}")
    results = []
    for values in itertools.product(*GRID.values()):
        params = dataclasses.replace(DEFAULT, **dict(zip(GRID, values, strict=True)))
        results.append((mean_scores(tuning, params), params))
    results.sort(key=lambda r: -float(r[0][0]))

    print("\nTop settings on the TUNING clips (majmin, root):")
    for (majmin, root), params in results[:10]:
        print(f"  {majmin:.3f} {root:.3f}  {params}")
    print("\nOn the HELD-OUT test clips:")
    for label, params in (("defaults", DEFAULT), ("best on tuning", results[0][1])):
        majmin, root = mean_scores(test, params)
        print(f"  {label:15s} test majmin {majmin:.3f} root {root:.3f}")


if __name__ == "__main__":
    main()
