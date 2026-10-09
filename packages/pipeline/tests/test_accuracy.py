"""Accuracy suite: full pipeline on annotated clips, scored with mir_eval, against a baseline.

    make test-accuracy                     # run and print the table
    UPDATE_BASELINE=1 make test-accuracy   # accept new numbers (review the diff!)

A metric may not drop more than TOLERANCE below its baseline. Improvements don't fail, but the
baseline should be raised in the same commit so later changes can't quietly give them back.
"""

import json
import os
from pathlib import Path

import numpy as np
import pytest
from accuracy_eval import Clip, clips, evaluate

from pipeline.stages import default_stages
from pipeline.version import pipeline_version

pytestmark = pytest.mark.accuracy

BASELINE = Path(__file__).parent / "accuracy_baseline.json"
TOLERANCE = 0.02  # absorbs tiny numeric differences between machines (e.g. macOS vs Linux CI)
CLIPS = clips()


def mean_by_instrument(results: dict[str, dict[str, float]]) -> dict[str, dict[str, float]]:
    means: dict[str, dict[str, float]] = {}
    for instrument in sorted({c.instrument for c in CLIPS}):
        rows = [results[c.name] for c in CLIPS if c.instrument is instrument]
        metrics = sorted({m for row in rows for m in row})
        means[str(instrument)] = {  # over the clips that have the metric (chords: comp only)
            m: round(float(np.mean([row[m] for row in rows if m in row])), 4) for m in metrics
        }
    return means


def report(results: dict[str, dict[str, float]]) -> str:
    metrics = sorted({m for row in results.values() for m in row})
    lines = ["| clip | " + " | ".join(metrics) + " |", "|---" * (len(metrics) + 1) + "|"]
    for name, row in results.items():
        cells = " | ".join(f"{row[m]:.3f}" if m in row else "" for m in metrics)
        lines.append(f"| {name} | {cells} |")
    for instrument, row in mean_by_instrument(results).items():
        cells = " | ".join(f"**{row[m]:.3f}**" if m in row else "" for m in metrics)
        lines.append(f"| **mean {instrument}** | {cells} |")
    return "\n".join(lines)


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> dict[str, dict[str, float]]:
    scored = {c.name: evaluate(c, tmp_path_factory.mktemp(c.name)) for c in CLIPS}
    print("\n" + report(scored))
    if os.environ.get("UPDATE_BASELINE") == "1":
        version = pipeline_version((s.name, s.version) for s in default_stages())
        baseline = {
            "pipeline_version": version,
            "tolerance": TOLERANCE,
            "clips": scored,
            "mean": mean_by_instrument(scored),
        }
        BASELINE.write_text(json.dumps(baseline, indent=1, sort_keys=True) + "\n")
    return scored


@pytest.mark.parametrize("clip", CLIPS, ids=[c.name for c in CLIPS])
def test_no_metric_dropped_below_baseline(clip: Clip, results: dict[str, dict[str, float]]) -> None:
    assert BASELINE.exists(), "no baseline yet: run UPDATE_BASELINE=1 make test-accuracy"
    expected = json.loads(BASELINE.read_text())["clips"][clip.name]
    drops = {
        metric: (value, expected[metric])
        for metric, value in results[clip.name].items()
        if value < expected.get(metric, 0.0) - TOLERANCE
    }
    assert not drops, f"{clip.name}: metric dropped (now, baseline): {drops}"
