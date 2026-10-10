import json
from fractions import Fraction
from pathlib import Path

import pytest

from pipeline.config import Instrument
from pipeline.edits import (
    Add,
    Delete,
    EditableScore,
    EditList,
    NoteRef,
    SetDuration,
    SetPitch,
    SetPosition,
    apply_edits,
    render,
)
from pipeline.errors import InvalidInputError
from pipeline.score import KeySignature, Score, ScoreNote
from pipeline.stages.tab import TabFile, TabNote

pytestmark = pytest.mark.unit

STANDARD = [40, 45, 50, 55, 59, 64]
F = Fraction


def doc(notes: list[tuple[int, Fraction, Fraction, int, int]]) -> EditableScore:
    """Guitar document from (pitch, onset, duration, string, fret); 120 bpm from 0 s."""
    return EditableScore(
        instrument=Instrument.GUITAR,
        score=Score(
            tempo_bpm=120.0,
            beats_per_bar=4,
            beat_unit=4,
            pickup_beats=0,
            key=KeySignature(tonic=0, mode="major", fifths=0),
            beat_times_s=[0.5 * b for b in range(9)],
            notes=[
                ScoreNote(pitch=p, velocity=80, onset_beats=o, duration_beats=d,
                          onset_s=float(o) / 2, offset_s=float(o + d) / 2)
                for p, o, d, _, _ in notes
            ],
        ),
        tab=TabFile(
            tuning=STANDARD,
            capo=0,
            notes=[TabNote(onset_beats=o, pitch=p, string=s, fret=f) for p, o, _, s, f in notes],
        ),
        trim_start_s=0.25,
    )  # fmt: skip


def at(onset: Fraction | int, pitch: int) -> NoteRef:
    return NoteRef(onset_beats=F(onset), pitch=pitch)


E4_OPEN = (64, F(0), F(1), 1, 0)  # high E, open
C4 = (60, F(1), F(1), 2, 1)  # B string, fret 1


def positions(d: EditableScore) -> dict[tuple[Fraction, int], tuple[int, int]]:
    assert d.tab is not None
    return {(t.onset_beats, t.pitch): (t.string, t.fret) for t in d.tab.notes}


def test_set_position_moves_the_same_note_to_another_string() -> None:
    edited = apply_edits(doc([E4_OPEN]), [SetPosition(note=at(0, 64), string=2, fret=5)])

    assert positions(edited) == {(F(0), 64): (2, 5)}
    assert [n.pitch for n in edited.score.notes] == [64]


def test_set_position_must_keep_the_pitch() -> None:
    with pytest.raises(InvalidInputError, match=r"Change 1: .*isn't the same note"):
        apply_edits(doc([E4_OPEN]), [SetPosition(note=at(0, 64), string=2, fret=4)])


def test_two_notes_at_once_cannot_share_a_string() -> None:
    chord = doc([E4_OPEN, (59, F(0), F(1), 2, 0)])  # E4 and B3 together
    with pytest.raises(InvalidInputError, match="already on string 2"):
        apply_edits(chord, [SetPosition(note=at(0, 64), string=2, fret=5)])


def test_set_pitch_keeps_the_string_when_it_can() -> None:
    edited = apply_edits(doc([C4]), [SetPitch(note=at(1, 60), pitch=62)])

    assert positions(edited) == {(F(1), 62): (2, 3)}
    assert [n.pitch for n in edited.score.notes] == [62]


def test_set_pitch_finds_another_string_when_the_old_one_cannot_play_it() -> None:
    edited = apply_edits(doc([E4_OPEN]), [SetPitch(note=at(0, 64), pitch=50)])  # D3: below high E

    ((_, (string, fret)),) = positions(edited).items()
    assert STANDARD[6 - string] + fret == 50


def test_delete_removes_the_note_and_its_position() -> None:
    edited = apply_edits(doc([E4_OPEN, C4]), [Delete(note=at(0, 64))])

    assert [n.pitch for n in edited.score.notes] == [60]
    assert list(positions(edited)) == [(F(1), 60)]


def test_add_places_a_note_with_timing_and_a_position() -> None:
    edited = apply_edits(
        doc([E4_OPEN]), [Add(onset_beats=F(2), duration_beats=F(1, 2), pitch=67, string=1)]
    )
    added = next(n for n in edited.score.notes if n.pitch == 67)

    assert (added.onset_s, added.offset_s) == (1.0, 1.25)
    assert positions(edited)[(F(2), 67)] == (1, 3)


def test_add_without_a_string_uses_a_free_one() -> None:
    edited = apply_edits(
        doc([E4_OPEN]),
        [Add(onset_beats=F(0), duration_beats=F(1), pitch=59)],  # with the open E
    )

    string, fret = positions(edited)[(F(0), 59)]
    assert string != 1 and STANDARD[6 - string] + fret == 59


def test_set_duration_changes_length_and_end_time() -> None:
    edited = apply_edits(doc([C4]), [SetDuration(note=at(1, 60), duration_beats=F(3))])

    (note,) = edited.score.notes
    assert (note.duration_beats, note.offset_s) == (F(3), 2.0)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (Delete(note=at(3, 64)), "isn't in this version"),
        (Add(onset_beats=F(0), duration_beats=F(1), pitch=64), "already that note"),
        (Add(onset_beats=F(1, 5), duration_beats=F(1), pitch=60), "sixteenths or triplets"),
        (SetDuration(note=at(0, 64), duration_beats=F(100)), "too long"),
        (SetPosition(note=at(0, 64), string=7, fret=0), "doesn't exist"),
        (Add(onset_beats=F(2), duration_beats=F(1), pitch=30, string=6), "can't play"),
    ],
)
def test_bad_edits_are_refused_with_a_message(edit: object, message: str) -> None:
    with pytest.raises(InvalidInputError, match=message):
        apply_edits(doc([E4_OPEN]), [edit])  # type: ignore[list-item]


def test_a_bad_edit_names_its_position_and_changes_nothing() -> None:
    original = doc([E4_OPEN, C4])
    with pytest.raises(InvalidInputError, match="Change 2:"):
        apply_edits(original, [Delete(note=at(1, 60)), Delete(note=at(1, 60))])
    assert len(original.score.notes) == 2


def test_edit_lists_parse_from_json_with_fraction_strings() -> None:
    raw = json.dumps(
        {
            "edits": [
                {
                    "op": "set_position",
                    "note": {"onset_beats": "1", "pitch": 60},
                    "string": 3,
                    "fret": 5,
                },
                {"op": "add", "onset_beats": "3/2", "duration_beats": "1/3", "pitch": 62},
            ]
        }
    )
    edits = EditList.model_validate_json(raw).edits

    assert isinstance(edits[0], SetPosition) and isinstance(edits[1], Add)
    assert edits[1].onset_beats == F(3, 2)


def test_render_writes_every_file_and_the_added_note(tmp_path: Path) -> None:
    edited = apply_edits(
        doc([E4_OPEN]), [Add(onset_beats=F(5), duration_beats=F(1), pitch=67, string=1)]
    )
    files = render(edited, tmp_path)

    assert set(files) == {
        "score.json",
        "score.musicxml",
        "quantized.mid",
        "sync.json",
        "tab.musicxml",
    }
    tab_xml = files["tab.musicxml"].read_text()
    assert "<fret>3</fret>" in tab_xml and tab_xml.count("<measure ") == 2  # beat 5 is in bar 2
    assert json.loads(files["sync.json"].read_text()) == {"bar_starts_ms": [250, 2250]}
    assert EditableScore.model_validate_json(files["score.json"].read_text()) == edited
