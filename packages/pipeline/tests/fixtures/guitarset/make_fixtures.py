"""Build the GuitarSet accuracy fixtures: 20 s excerpts plus ground truth (CC BY 4.0).

    uv run python packages/pipeline/tests/fixtures/guitarset/make_fixtures.py

Reads only the needed files straight out of the Zenodo zips with HTTP range requests (a few MB
instead of ~700 MB). Writes, per track, `<track>.flac` (mic audio, mono, 44.1 kHz) and
`<track>.truth.json` (notes with string/fret, beats, performed chords), plus ATTRIBUTION.md.
"""

import io
import json
import math
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

import soundfile

HERE = Path(__file__).parent
ZENODO = "https://zenodo.org/records/3371780/files/"  # GuitarSet 1.1.0
EXCERPT_S = 20.0
LEAD_IN_S = 0.5  # start a little before the first note
STANDARD_TUNING = (40, 45, 50, 55, 59, 64)  # GuitarSet's tuning; data_source "0" = low E string
# (player, style, comp|solo): six players, five styles, both accompaniment and lead playing.
SELECTION = [
    (0, "BN", "comp"),
    (1, "Funk", "solo"),
    (2, "Jazz", "comp"),
    (3, "Rock", "solo"),
    (4, "SS", "comp"),
    (5, "BN", "solo"),
]


class HttpRangeFile(io.RawIOBase):
    """A seekable read-only file over HTTP range requests, so zipfile can read single members."""

    def __init__(self, url: str) -> None:
        self.url, self.pos = url, 0
        with urllib.request.urlopen(urllib.request.Request(url, method="HEAD")) as response:
            self.size = int(response.headers["Content-Length"])

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def readinto(self, buffer: Any) -> int:
        if self.pos >= self.size:
            return 0
        end = min(self.pos + len(buffer), self.size) - 1
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={self.pos}-{end}"})
        with urllib.request.urlopen(request) as response:
            data = response.read()
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)


def remote_zip(name: str) -> zipfile.ZipFile:
    return zipfile.ZipFile(io.BufferedReader(HttpRangeFile(f"{ZENODO}{name}?download=1"), 1 << 16))


def truth_from_jams(jams: dict[str, Any], start: float) -> dict[str, Any]:
    notes, beats, downbeats, chords, tempo = [], [], [], [], None
    for annotation in jams["annotations"]:
        namespace = annotation["namespace"]
        if namespace == "note_midi":
            string_index = int(annotation["annotation_metadata"]["data_source"])
            for obs in annotation["data"]:
                onset = obs["time"] - start
                if 0 <= onset < EXCERPT_S:
                    pitch = round(obs["value"])
                    notes.append(
                        {
                            "onset_s": round(onset, 4),
                            "offset_s": round(min(onset + obs["duration"], EXCERPT_S), 4),
                            "pitch": pitch,
                            "string": 6 - string_index,  # 1 = high E, as written in tab
                            "fret": pitch - STANDARD_TUNING[string_index],
                        }
                    )
        elif namespace == "beat_position":
            for obs in annotation["data"]:
                t = obs["time"] - start
                if 0 <= t < EXCERPT_S:
                    beats.append(round(t, 4))
                    if obs["value"]["position"] == 1:
                        downbeats.append(round(t, 4))
        elif namespace == "chord" and annotation["annotation_metadata"]["data_source"]:
            # Two chord annotations: the lead sheet's (no data_source) and the chords actually
            # played, transcribed from the notes. Keep the played ones.
            for obs in annotation["data"]:
                on, off = obs["time"] - start, obs["time"] + obs["duration"] - start
                if off > 0 and on < EXCERPT_S:
                    chords.append(
                        {
                            "onset_s": round(max(on, 0.0), 4),
                            "offset_s": round(min(off, EXCERPT_S), 4),
                            "label": obs["value"],
                        }
                    )
        elif namespace == "tempo" and tempo is None:
            tempo = float(annotation["data"][0]["value"])
    notes.sort(key=lambda n: (n["onset_s"], n["pitch"]))
    return {
        "tempo_bpm": tempo,
        "notes": notes,
        "beats_s": beats,
        "downbeats_s": downbeats,
        "chords": chords,
    }


def main() -> None:
    annotations, audio = remote_zip("annotation.zip"), remote_zip("audio_mono-mic.zip")
    names = sorted(n for n in annotations.namelist() if n.endswith(".jams"))
    for player, style, mode in SELECTION:
        jams_name = next(
            n
            for n in names
            if n.startswith(f"{player:02d}_{style}") and n.endswith(f"_{mode}.jams")
        )
        track = jams_name.removesuffix(".jams")
        jams = json.loads(annotations.read(jams_name))
        first_onset = min(
            obs["time"]
            for a in jams["annotations"]
            if a["namespace"] == "note_midi"
            for obs in a["data"]
        )
        start = max(0.0, math.floor((first_onset - LEAD_IN_S) * 10) / 10)

        samples, rate = soundfile.read(io.BytesIO(audio.read(f"{track}_mic.wav")), dtype="float32")
        excerpt = samples[int(start * rate) : int((start + EXCERPT_S) * rate)]
        soundfile.write(HERE / f"{track}.flac", excerpt, rate, subtype="PCM_16", format="FLAC")

        truth = {
            "track": track,
            "source": "GuitarSet 1.1.0, audio_mono-mic, https://zenodo.org/records/3371780",
            "license": "CC BY 4.0",
            "start_s": start,
            "duration_s": EXCERPT_S,
            **truth_from_jams(jams, start),
        }
        (HERE / f"{track}.truth.json").write_text(json.dumps(truth, indent=1) + "\n")
        print(f"{track}: {len(truth['notes'])} notes, {len(truth['beats_s'])} beats")


if __name__ == "__main__":
    main()
