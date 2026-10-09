import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from pipeline.config import Instrument, PipelineConfig
from pipeline.musicxml import DIVISIONS, write_score
from pipeline.runner import run_pipeline
from pipeline.score import ChordSymbol, KeySignature, Score, ScoreNote
from pipeline.stages import default_stages
from pipeline.stages.notation import Notation

pytestmark = pytest.mark.unit

GUITAR, PIANO = Instrument.GUITAR, Instrument.PIANO
THIRD = Fraction(1, 3)


def make_score(
    notes: Sequence[tuple[int, Fraction | int, Fraction | int]],
    pickup: int = 0,
    fifths: int = 0,
) -> Score:
    return Score(
        tempo_bpm=100.0,
        beats_per_bar=4,
        beat_unit=4,
        pickup_beats=pickup,
        key=KeySignature(tonic=0, mode="major", fifths=fifths),
        beat_times_s=[],
        notes=[
            ScoreNote(
                pitch=p,
                velocity=80,
                onset_beats=Fraction(o),
                duration_beats=Fraction(d),
                onset_s=0.0,
                offset_s=0.0,
            )
            for p, o, d in notes
        ],
    )


def parse(xml: bytes) -> ET.Element:
    return ET.fromstring(xml.split(b"\n", 2)[2])  # skip the XML declaration and DOCTYPE


def measures(xml: bytes) -> list[ET.Element]:
    return parse(xml).findall("./part/measure")


def staff_durations(measure: ET.Element) -> dict[str, int]:
    totals: dict[str, int] = {}
    for note in measure.findall("note"):
        if note.find("chord") is None:
            staff = note.findtext("staff", "1")
            totals[staff] = totals.get(staff, 0) + int(note.findtext("duration", "0"))
    return totals


def tie_types(note: ET.Element) -> list[str | None]:
    return [t.get("type") for t in note.findall("tie")]


def random_score(seed: int) -> Score:
    rng = np.random.default_rng(seed)
    notes, beat = [], Fraction(0)
    while beat < 24:
        grid = 3 if rng.random() < 0.25 else 4
        for step in range(grid):
            if rng.random() < 0.6:
                onset = beat + Fraction(step, grid)
                duration = Fraction(int(rng.integers(1, 3 * grid)), grid)
                notes.append((int(rng.integers(40, 85)), onset, duration))
        beat += 1
    return make_score(notes, pickup=int(rng.integers(0, 4)), fifths=int(rng.integers(-6, 7)))


@pytest.mark.parametrize("instrument", [GUITAR, PIANO])
@pytest.mark.parametrize("seed", range(25))
def test_every_bar_adds_up_and_ties_and_tuplets_pair_up(seed: int, instrument: Instrument) -> None:
    score = random_score(seed)
    xml = write_score(score, instrument)

    for i, measure in enumerate(measures(xml)):
        expected = (score.pickup_beats if i == 0 and score.pickup_beats else 4) * DIVISIONS
        assert set(staff_durations(measure).values()) == {expected}, f"bar {i}"
    text = xml.decode()
    assert text.count('<tie type="start"') == text.count('<tie type="stop"')
    assert text.count('<tuplet type="start"') == text.count('<tuplet type="stop"')


def test_output_is_byte_identical_across_runs() -> None:
    score = random_score(7)
    assert write_score(score, PIANO) == write_score(score, PIANO)


def test_pickup_bar_is_implicit_bar_zero() -> None:
    bars = measures(write_score(make_score([(64, 0, 1), (67, 1, 4)], pickup=1), GUITAR))

    assert (bars[0].get("number"), bars[0].get("implicit")) == ("0", "yes")
    assert staff_durations(bars[0]) == {"1": 12}
    assert bars[1].get("number") == "1"


def test_note_across_a_bar_line_is_tied() -> None:
    bars = measures(write_score(make_score([(60, 3, 2)]), GUITAR))
    last_of_first, first_of_second = bars[0].findall("note")[-1], bars[1].findall("note")[0]

    assert tie_types(last_of_first) == ["start"]
    assert tie_types(first_of_second) == ["stop"]
    assert first_of_second.findtext("type") == "quarter"


def test_syncopated_note_is_split_at_the_beat() -> None:
    notes = measures(write_score(make_score([(60, Fraction(1, 2), 1)]), GUITAR))[0].findall("note")
    sounding = [n for n in notes if n.find("rest") is None]

    assert [n.findtext("type") for n in sounding] == ["eighth", "eighth"]
    assert [tie_types(n) for n in sounding] == [["start"], ["stop"]]


def test_triplets_get_time_modification_and_one_bracket() -> None:
    score = make_score([(60, 0, THIRD), (62, THIRD, THIRD), (64, 2 * THIRD, THIRD)])
    xml = write_score(score, GUITAR)
    notes = measures(xml)[0].findall("note")[:3]

    assert all(n.findtext("time-modification/actual-notes") == "3" for n in notes)
    assert [n.findtext("type") for n in notes] == ["eighth"] * 3
    assert xml.decode().count('<tuplet type="start"') == 1


@pytest.mark.parametrize(("fifths", "step", "alter"), [(0, "D", "1"), (-3, "E", "-1")])
def test_black_keys_are_spelled_for_the_key(fifths: int, step: str, alter: str) -> None:
    score = make_score([(63, 0, 1)], fifths=fifths)
    note = measures(write_score(score, GUITAR))[0].findall("note")[0]

    assert (note.findtext("pitch/step"), note.findtext("pitch/alter")) == (step, alter)


def test_piano_splits_hands_at_middle_c() -> None:
    xml = write_score(make_score([(72, 0, 4), (48, 0, 4)]), PIANO)
    staff_of = {
        f"{n.findtext('pitch/step')}{n.findtext('pitch/octave')}": n.findtext("staff")
        for n in measures(xml)[0].findall("note")
        if n.find("pitch") is not None
    }

    assert staff_of == {"C5": "1", "C3": "2"}
    assert b"<staves>2</staves>" in xml and b"<backup>" in xml


def test_guitar_uses_octave_treble_clef() -> None:
    clef = parse(write_score(make_score([(52, 0, 1)]), GUITAR)).find(".//clef")

    assert clef is not None and clef.findtext("clef-octave-change") == "-1"


def golden_score() -> Score:
    return make_score(
        [
            (64, 0, Fraction(1, 2)),
            (67, Fraction(1, 2), Fraction(1, 2)),
            (69, 1, THIRD),
            (71, 1 + THIRD, THIRD),
            (72, 1 + 2 * THIRD, THIRD),
            (52, 2, 2),
            (59, 2, 2),
            (64, 2, 2),
            (76, 4 + Fraction(3, 4), Fraction(5, 4)),
            (45, 7, 3),
        ],
        fifths=1,
    )


@pytest.mark.parametrize("instrument", [GUITAR, PIANO])
def test_golden_musicxml(instrument: Instrument, golden: Callable[[str, bytes], None]) -> None:
    golden(f"notation_{instrument}.musicxml", write_score(golden_score(), instrument))


def test_notation_stage_through_the_whole_pipeline(tmp_path: Path) -> None:
    source = Path(__file__).parent / "fixtures" / "basic_pitch" / "piano_like.wav"
    cfg = PipelineConfig(instrument=Instrument.PIANO)
    notation = run_pipeline(source, tmp_path, cfg, default_stages()).output(Notation)
    xml = (tmp_path / notation.musicxml.path).read_bytes()

    assert notation.measures == len(measures(xml)) > 0
    for i, measure in enumerate(measures(xml)):
        assert len(set(staff_durations(measure).values())) == 1, f"bar {i}"


def test_chord_names_are_written_as_harmony_where_they_start() -> None:
    chords = [
        ChordSymbol(root=3, quality="maj", onset_beats=Fraction(0), duration_beats=Fraction(2),
                    onset_s=0.0, offset_s=1.0),
        ChordSymbol(root=8, quality="min7", onset_beats=Fraction(3), duration_beats=Fraction(1),
                    onset_s=1.5, offset_s=2.0),
    ]  # fmt: skip
    score = make_score([(63, 0, 2), (68, 2, 2)], fifths=-3).model_copy(update={"chords": chords})
    measure = measures(write_score(score, GUITAR))[0]
    children = [child.tag for child in measure if child.tag in {"harmony", "note"}]
    harmonies = measure.findall("harmony")

    assert children == ["harmony", "note", "harmony", "note"]
    assert [h.findtext("root/root-step") for h in harmonies] == ["E", "A"]
    assert [h.findtext("root/root-alter") for h in harmonies] == ["-1", "-1"]
    assert [(h.findtext("kind"), h.find("kind").get("text")) for h in harmonies] == [  # type: ignore[union-attr]
        ("major", ""),
        ("minor-seventh", "m7"),
    ]
    assert [h.findtext("offset") for h in harmonies] == [None, str(DIVISIONS)]  # beat 3 = 1 in
