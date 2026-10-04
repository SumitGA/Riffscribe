"""Download a GuitarSet *tuning* set: excerpts that never appear in the committed test clips.

    uv run python packages/pipeline/tests/tuning/make_tuning_set.py [--count 24]

Settings are tuned on these and judged on tests/fixtures/guitarset, so tuning can't overfit the
test clips. Written to ~/.cache/tabscribe/guitarset-tuning (not committed; CC BY 4.0).
"""

import argparse
import io
import json
import math
import random
import sys
from pathlib import Path

import soundfile

sys.path.insert(0, str(Path(__file__).parents[1]))  # the tests dir
from fixtures.guitarset.make_fixtures import (
    EXCERPT_S,
    LEAD_IN_S,
    remote_zip,
    truth_from_jams,
)
from fixtures.guitarset.make_fixtures import (
    HERE as TEST_FIXTURES,
)

CACHE = Path.home() / ".cache" / "tabscribe" / "guitarset-tuning"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=24)
    args = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    test_tracks = {p.name.removesuffix(".truth.json") for p in TEST_FIXTURES.glob("*.truth.json")}

    annotations, audio = remote_zip("annotation.zip"), remote_zip("audio_mono-mic.zip")
    names = sorted(n.removesuffix(".jams") for n in annotations.namelist() if n.endswith(".jams"))
    # Seeded, balanced between comp and solo, and never a test track.
    pool = [n for n in names if n not in test_tracks]
    random.Random(2026).shuffle(pool)
    chosen = [n for n in pool if n.endswith("_comp")][: args.count // 2]
    chosen += [n for n in pool if n.endswith("_solo")][: args.count - len(chosen)]

    for track in sorted(chosen):
        if (CACHE / f"{track}.truth.json").exists():
            continue
        jams = json.loads(annotations.read(f"{track}.jams"))
        first = min(
            o["time"]
            for a in jams["annotations"]
            if a["namespace"] == "note_midi"
            for o in a["data"]
        )
        start = max(0.0, math.floor((first - LEAD_IN_S) * 10) / 10)
        samples, rate = soundfile.read(io.BytesIO(audio.read(f"{track}_mic.wav")), dtype="float32")
        excerpt = samples[int(start * rate) : int((start + EXCERPT_S) * rate)]
        soundfile.write(CACHE / f"{track}.flac", excerpt, rate, subtype="PCM_16", format="FLAC")
        truth = {"track": track, "start_s": start, **truth_from_jams(jams, start)}
        (CACHE / f"{track}.truth.json").write_text(json.dumps(truth) + "\n")
        print(f"{track}: {len(truth['notes'])} notes", flush=True)


if __name__ == "__main__":
    main()
