"""Grid-search when notes a little apart are one strummed chord (rhythm.StrumParams).

    uv run python packages/pipeline/tests/tuning/make_tuning_set.py --count 48   # once
    uv run python packages/pipeline/tests/tuning/tune_strums.py

Each clip is transcribed once (cached); every setting then reruns only the quantizer. Two
scores from accuracy_eval.grid_grouping pull against each other: `chords_whole` (the player's
strums written at one grid position) and `notes_apart` (separate notes not merged into fake
chords). Settings are ranked on the tuning clips by their mean, and rejected if notes_apart
falls more than MAX_APART_LOSS below today's rule; the committed test clips (GuitarSet and the
held-out Guitar-TECHS) are scored at the end as an unbiased check.
"""

import itertools
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parents[1]))  # the tests dir
from accuracy_eval import grid_grouping
from tuning.make_tuning_set import CACHE

from pipeline.config import Instrument, PipelineConfig
from pipeline.rhythm import StrumParams, TimedNote, quantize
from pipeline.runner import run_pipeline
from pipeline.stages import default_stages
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import track_beats
from pipeline.stages.transcribe import NoteEvents, NoteList

FIXTURES = Path(__file__).parents[1] / "fixtures"
WORK = CACHE / "work"
MAX_APART_LOSS = 0.01
# Second pass (the first, gap 0.05-0.1 / span 0.15-0.25 / ring 0-0.08, scored strums whose
# strings were at most 60 ms apart and missed the slow ones). Best: gap 0.09, span 0.2, ring
# 0.05: test chords_whole 0.52 -> 0.74, notes_apart 0.993 -> 0.986. Longer spans change
# nothing; gaps of 0.1 or more merge separate notes beyond MAX_APART_LOSS.
GRID: dict[str, list[float]] = {
    "gap_s": [0.07, 0.08, 0.09, 0.1, 0.12, 0.14],
    "span_s": [0.2, 0.25, 0.3, 0.35],
    "min_ring_s": [0.0, 0.05, 0.1],
}


def load(truth_paths: list[Path]) -> list[dict[str, Any]]:
    """Per clip: our transcribed notes, beat times and the annotation (pipeline run once)."""
    clips = []
    for truth_path in truth_paths:
        truth = json.loads(truth_path.read_text())
        audio = truth_path.with_name(truth_path.name.replace(".truth.json", ".flac"))
        work = WORK / truth.get("track", truth_path.name.removesuffix(".truth.json"))
        result = run_pipeline(
            audio, work, PipelineConfig(instrument=Instrument.GUITAR), default_stages()[:3]
        )
        events = result.output(NoteEvents)
        notes = NoteList.model_validate_json((work / events.notes.path).read_text()).notes
        envelope = np.load(work / events.onset_envelope.path).astype(np.float64)
        clips.append(
            {
                "name": truth_path.name.removesuffix(".truth.json"),
                "notes": [TimedNote(n.onset_s, n.offset_s, n.pitch, n.velocity) for n in notes],
                "beats": track_beats(envelope, events.envelope_fps, notes),
                "shift": result.output(NormalizedAudio).trim_start_s,
                "ref": truth["notes"],
            }
        )
    return clips


def scores(clip: dict[str, Any], params: StrumParams | None) -> dict[str, float]:
    rhythm = quantize(clip["notes"], clip["beats"], params)
    shift = clip["shift"]
    est = [(n.onset_s + shift, n.offset_s + shift, n.pitch, n.onset_beats) for n in rhythm.notes]
    return grid_grouping(clip["ref"], est)


def mean(clips: list[dict[str, Any]], params: StrumParams | None) -> dict[str, float]:
    rows = [scores(c, params) for c in clips]
    return {
        m: round(float(np.mean([r[m] for r in rows if m in r])), 4)
        for m in ("chords_whole", "notes_apart")
    }


def main() -> None:
    tuning = load(sorted(CACHE.glob("*.truth.json")))
    today = mean(tuning, None)
    print(f"today's rule (35 ms rolls): {today}")
    results = []
    for values in itertools.product(*GRID.values()):
        params = replace(StrumParams(), **dict(zip(GRID, values, strict=True)))
        m = mean(tuning, params)
        if m["notes_apart"] >= today["notes_apart"] - MAX_APART_LOSS:
            results.append((m["chords_whole"] + m["notes_apart"], m, params))
    results.sort(key=lambda r: -r[0])
    for _, m, params in results[:8]:
        print(f"{m}  gap {params.gap_s} span {params.span_s} ring {params.min_ring_s}")

    best = results[0][2]
    test = load(
        sorted(FIXTURES.glob("guitarset/*.truth.json"))
        + sorted(FIXTURES.glob("guitar_techs/*.truth.json"))
    )
    print(f"\ntest clips, today: {mean(test, None)}")
    print(f"test clips, best:  {mean(test, best)}  ({best})")
    print(f"test clips, default StrumParams(): {mean(test, StrumParams())}")


if __name__ == "__main__":
    main()
