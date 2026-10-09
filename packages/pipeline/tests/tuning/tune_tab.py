"""Grid-search tab fingering weights on the tuning set; judge on held-out clips.

    uv run python packages/pipeline/tests/tuning/make_tuning_set.py --count 48   # once
    uv run python packages/pipeline/tests/tuning/tune_tab.py [--write-prior]

`--write-prior` first rewrites pipeline/models/tab_prior/string_counts.json: how often the
players used each string for each pitch, counted from the tuning clips' annotations only.

Fingering is tuned on the pipeline's own transcription (run once per clip up to quantize,
cached), not on the annotated notes: stray and missing notes are what pull the hand to the
wrong place, and annotated notes hide that. Score: of our notes that match an annotated note,
the share on the player's string. Settings are ranked on the tuning clips (comp and solo
weighted equally); the committed test clips are scored at the end as an unbiased check.
"""

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any

import mir_eval
import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))  # the tests dir
from accuracy_eval import _hz, _intervals
from tuning.make_tuning_set import CACHE

from pipeline.config import Instrument, PipelineConfig, Tuning
from pipeline.runner import run_pipeline
from pipeline.score import Score
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import QuantizedScore
from pipeline.tab import TUNINGS, assign_tab, string_counts

TEST_DIR = Path(__file__).parents[1] / "fixtures" / "guitarset"
PRIOR_FILE = Path(__file__).parents[2] / "src/pipeline/models/tab_prior/string_counts.json"
WORK = CACHE / "work"
# Fourth pass. Passes without the position prior (fret height 0-0.5, span 1-3, movement
# 0.25-3, shift 0.5-6) peaked at fret height 0.02, span 2, movement 1, shift 2; with it (prior
# 0-2, fret height 0-0.1, span 1-2, movement 0.5-2, shift 1-4) at prior 1, fret height 0,
# span 1, movement 1, shift 4, so this one extends past span 1 and shift 4.
GRID: dict[str, list[float]] = {
    "prior_weight": [0.75, 1.0, 1.5],
    "fret_height": [0.0],
    "span": [0.5, 1.0],
    "movement": [0.5, 1.0],
    "shift": [3.0, 4.0, 6.0, 8.0],
}
FIXED = {"open_string": 0.0}  # any open-string bonus cost solo accuracy on annotated notes


def load(directory: Path) -> list[dict[str, Any]]:
    """Per clip: quantized notes, and which annotated note each one matches (computed once)."""
    clips = []
    for truth_path in sorted(directory.glob("*.truth.json")):
        truth = json.loads(truth_path.read_text())
        audio = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
        work = WORK / truth["track"]
        cfg = PipelineConfig(instrument=Instrument.GUITAR)
        result = run_pipeline(audio, work, cfg, default_stages()[:4])  # up to quantize
        shift = result.output(NormalizedAudio).trim_start_s
        notes = Score.model_validate_json(
            (work / result.output(QuantizedScore).score.path).read_text()
        ).notes
        ref = truth["notes"]
        pairs = mir_eval.transcription.match_notes(
            _intervals([(n["onset_s"], n["offset_s"]) for n in ref]),
            _hz([n["pitch"] for n in ref]),
            _intervals([(n.onset_s + shift, n.offset_s + shift) for n in notes]),
            _hz([n.pitch for n in notes]),
            offset_ratio=None,
        )
        strings = {e: ref[r]["string"] for r, e in pairs}
        mode = "comp" if truth["track"].endswith("_comp") else "solo"
        clips.append({"notes": notes, "strings": strings, "mode": mode})
    return clips


def write_prior(directory: Path) -> None:
    standard = TUNINGS[Tuning.STANDARD]
    counts: dict[int, list[int]] = {}
    for truth_path in sorted(directory.glob("*.truth.json")):
        for note in json.loads(truth_path.read_text())["notes"]:
            string_index = len(standard) - note["string"]  # truth: 1 = high E
            counts.setdefault(note["pitch"], [0] * len(standard))[string_index] += 1
    rows = ",\n".join(f'  "{p}": {json.dumps(counts[p])}' for p in sorted(counts))
    about = (
        "Notes per string (lowest first) for each MIDI pitch, from the annotations of GuitarSet "
        "tuning excerpts (CC BY 4.0); see README.md."
    )
    PRIOR_FILE.write_text(f'{{\n "about": {json.dumps(about)},\n "counts": {{\n{rows}\n }}\n}}\n')
    string_counts.cache_clear()


def accuracy(clip: dict[str, Any], weights: dict[str, float]) -> float:
    weights = dict(weights)
    prior_weight = weights.pop("prior_weight", 1.0)
    positions = assign_tab(clip["notes"], Tuning.STANDARD, 0, weights, prior_weight)
    notes = clip["notes"]
    found = [
        positions[key].string == string
        for e, string in clip["strings"].items()
        if (key := (notes[e].onset_beats, notes[e].pitch)) in positions
    ]
    return float(np.mean(found)) if found else 0.0


def mean_scores(
    clips: list[dict[str, Any]], weights: dict[str, float]
) -> tuple[float, float, float]:
    by_mode = {
        mode: float(np.mean([accuracy(c, weights) for c in clips if c["mode"] == mode]))
        for mode in ("comp", "solo")
    }
    return (by_mode["comp"] + by_mode["solo"]) / 2, by_mode["comp"], by_mode["solo"]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write-prior", action="store_true")
    if parser.parse_args().write_prior:
        write_prior(CACHE)
    tuning, test = load(CACHE), load(TEST_DIR)
    print(f"tuning clips: {len(tuning)} | held-out test clips: {len(test)}")
    results = []
    for values in itertools.product(*GRID.values()):
        weights = FIXED | dict(zip(GRID, values, strict=True))
        results.append((mean_scores(tuning, weights), weights))
    results.sort(key=lambda r: -r[0][0])

    print("\nTop settings on the TUNING clips (mean, comp, solo):")
    for (mean, comp, solo), weights in results[:10]:
        print(f"  {mean:.3f} {comp:.3f} {solo:.3f}  {weights}")
    print("\nOn the HELD-OUT test clips:")
    for label, weights in (("defaults", {}), ("best on tuning", results[0][1])):
        mean, comp, solo = mean_scores(test, weights)
        print(f"  {label:15s} test mean {mean:.3f} comp {comp:.3f} solo {solo:.3f}")


if __name__ == "__main__":
    main()
