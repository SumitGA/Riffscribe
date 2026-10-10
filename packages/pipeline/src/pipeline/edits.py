"""User corrections to a transcription (ADR-0011): operations on a version's structured score.

A version's editable document (`EditableScore`, saved as `score.json`) holds the quantized
`Score`, the guitar tab positions, and the audio's trim offset (for `sync.json`). The app sends
operations against a base version; `apply_edits` applies and checks them, and `render` writes
the new version's files with the same writers the pipeline stages use.

Notes are addressed by `(onset_beats, pitch)`, which the quantizer makes unique. Beats are exact
fractions; positions must be on the writer's grid (twelfths of a beat: sixteenths and triplets).
"""

import json
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

from pipeline.config import Instrument, Tuning
from pipeline.errors import InvalidInputError
from pipeline.midi import write_notes
from pipeline.musicxml import DIVISIONS, TabLayout, write_score
from pipeline.rhythm import BeatMap
from pipeline.score import Score, ScoreNote
from pipeline.stages.notation import bar_starts_ms
from pipeline.stages.tab import TabFile, TabNote
from pipeline.stages.transcribe import GM_PROGRAM
from pipeline.tab import MAX_FRET, TUNINGS, assign_tab
from pipeline.types import Frozen

DEFAULT_VELOCITY = 80
MAX_NOTE_BEATS = Fraction(64)  # 16 bars of 4/4: longer is a typo, not music


class EditableScore(Frozen):
    """A version's editable document (score.json)."""

    instrument: Instrument
    score: Score
    tab: TabFile | None = None  # guitar only
    trim_start_s: float = 0.0  # the uploaded audio's trimmed lead-in, for sync.json


class NoteRef(Frozen):
    onset_beats: Fraction
    pitch: int = Field(ge=0, le=127)


class SetPosition(Frozen):
    """Play the same note on another string (tab only)."""

    op: Literal["set_position"] = "set_position"
    note: NoteRef
    string: int = Field(ge=1)  # 1 = highest string
    fret: int = Field(ge=0)


class SetPitch(Frozen):
    """Change a note's pitch; with a string, it's played there, else on the best string."""

    op: Literal["set_pitch"] = "set_pitch"
    note: NoteRef
    pitch: int = Field(ge=0, le=127)
    string: int | None = Field(default=None, ge=1)


class Delete(Frozen):
    op: Literal["delete"] = "delete"
    note: NoteRef


class Add(Frozen):
    """A new note; on guitar, with a string it's played there, else on the best string."""

    op: Literal["add"] = "add"
    onset_beats: Fraction = Field(ge=0)
    duration_beats: Fraction = Field(gt=0)
    pitch: int = Field(ge=0, le=127)
    string: int | None = Field(default=None, ge=1)


class SetDuration(Frozen):
    op: Literal["set_duration"] = "set_duration"
    note: NoteRef
    duration_beats: Fraction = Field(gt=0)


Edit = Annotated[SetPosition | SetPitch | Delete | Add | SetDuration, Field(discriminator="op")]


class EditList(Frozen):
    edits: list[Edit]


def apply_edits(doc: EditableScore, edits: Sequence[Edit]) -> EditableScore:
    """The document with every edit applied in order. Raises InvalidInputError on a bad edit,
    naming which one (1-based), so nothing is half-applied."""
    notes = {(n.onset_beats, n.pitch): n for n in doc.score.notes}
    positions = (
        {(t.onset_beats, t.pitch): (t.string, t.fret) for t in doc.tab.notes} if doc.tab else None
    )
    beat_map = BeatMap(doc.score.beat_times_s) if len(doc.score.beat_times_s) >= 2 else None

    for index, edit in enumerate(edits, start=1):
        try:
            _apply(doc, edit, notes, positions, beat_map)
        except InvalidInputError as error:
            raise InvalidInputError(f"Change {index}: {error.user_message}") from error

    ordered = sorted(notes.values(), key=lambda n: (n.onset_beats, n.pitch))
    tab = None
    if doc.tab is not None and positions is not None:
        tab = doc.tab.model_copy(
            update={
                "notes": [
                    TabNote(onset_beats=onset, pitch=pitch, string=string, fret=fret)
                    for (onset, pitch), (string, fret) in sorted(positions.items())
                ]
            }
        )
    return doc.model_copy(
        update={"score": doc.score.model_copy(update={"notes": ordered}), "tab": tab}
    )


def _apply(
    doc: EditableScore,
    edit: Edit,
    notes: dict[tuple[Fraction, int], ScoreNote],
    positions: dict[tuple[Fraction, int], tuple[int, int]] | None,
    beat_map: BeatMap | None,
) -> None:
    if isinstance(edit, Add):
        key = (edit.onset_beats, edit.pitch)
        _on_grid(edit.onset_beats, edit.duration_beats)
        if key in notes:
            raise InvalidInputError("there is already that note at that position")
        onset_s = _seconds(doc, beat_map, edit.onset_beats)
        notes[key] = ScoreNote(
            pitch=edit.pitch,
            velocity=DEFAULT_VELOCITY,
            onset_beats=edit.onset_beats,
            duration_beats=edit.duration_beats,
            onset_s=onset_s,
            offset_s=_seconds(doc, beat_map, edit.onset_beats + edit.duration_beats),
        )
        if positions is not None:
            positions[key] = _position(doc, notes[key], edit.string, positions)
        return

    key = (edit.note.onset_beats, edit.note.pitch)
    note = notes.get(key)
    if note is None:
        raise InvalidInputError("that note isn't in this version any more")

    if isinstance(edit, Delete):
        del notes[key]
        if positions is not None:
            positions.pop(key, None)
    elif isinstance(edit, SetDuration):
        _on_grid(note.onset_beats, edit.duration_beats)
        notes[key] = note.model_copy(
            update={
                "duration_beats": edit.duration_beats,
                "offset_s": _seconds(doc, beat_map, note.onset_beats + edit.duration_beats),
            }
        )
    elif isinstance(edit, SetPosition):
        if positions is None:
            raise InvalidInputError("only guitar scores have strings and frets")
        if _pitch_at(doc, edit.string, edit.fret) != note.pitch:
            raise InvalidInputError(
                f"string {edit.string}, fret {edit.fret} isn't the same note; "
                "change the pitch instead"
            )
        _free_string(positions, key, edit.string)
        positions[key] = (edit.string, edit.fret)
    elif isinstance(edit, SetPitch):
        new_key = (note.onset_beats, edit.pitch)
        if new_key != key and new_key in notes:
            raise InvalidInputError("there is already that note at that position")
        del notes[key]
        old_position = positions.pop(key, None) if positions is not None else None
        notes[new_key] = note.model_copy(update={"pitch": edit.pitch})
        if positions is not None:
            string = edit.string or (old_position[0] if old_position else None)
            if (
                edit.string is None
                and string is not None
                and _fret_for(doc, string, edit.pitch) is None
            ):
                string = None  # the note's old string can't play the new pitch: find another
            positions[new_key] = _position(doc, notes[new_key], string, positions)


def _on_grid(onset: Fraction, duration: Fraction) -> None:
    for value in (onset, duration):
        if (value * DIVISIONS).denominator != 1:
            raise InvalidInputError("notes must start and end on sixteenths or triplets")
    if duration > MAX_NOTE_BEATS:
        raise InvalidInputError("that note is too long")


def _seconds(doc: EditableScore, beat_map: BeatMap | None, beats: Fraction) -> float:
    """Where a beat falls in the audio, for playback and sync of added or changed notes."""
    if beat_map is not None:
        return round(max(0.0, beat_map.time_at(float(beats))), 4)
    start = doc.score.beat_times_s[0] if doc.score.beat_times_s else 0.0
    return round(max(0.0, start + float(beats) * 60.0 / doc.score.tempo_bpm), 4)


def _capo(doc: EditableScore) -> int:
    assert doc.tab is not None  # callers only get here for guitar documents
    return doc.tab.capo


def _open_strings(doc: EditableScore) -> list[int]:
    """Sounding open-string pitches with the capo, index 0 = string 1 (highest)."""
    assert doc.tab is not None
    return [p + doc.tab.capo for p in reversed(doc.tab.tuning)]


def _pitch_at(doc: EditableScore, string: int, fret: int) -> int | None:
    strings = _open_strings(doc)
    if not 1 <= string <= len(strings) or not 0 <= fret <= MAX_FRET - _capo(doc):
        raise InvalidInputError(f"string {string}, fret {fret} doesn't exist on this guitar")
    return strings[string - 1] + fret


def _fret_for(doc: EditableScore, string: int, pitch: int) -> int | None:
    strings = _open_strings(doc)
    if not 1 <= string <= len(strings):
        return None
    fret = pitch - strings[string - 1]
    return fret if 0 <= fret <= MAX_FRET - _capo(doc) else None


def _free_string(
    positions: dict[tuple[Fraction, int], tuple[int, int]], key: tuple[Fraction, int], string: int
) -> None:
    for other, (other_string, _) in positions.items():
        if other != key and other[0] == key[0] and other_string == string:
            raise InvalidInputError(f"another note at that moment is already on string {string}")


def _position(
    doc: EditableScore,
    note: ScoreNote,
    string: int | None,
    positions: dict[tuple[Fraction, int], tuple[int, int]],
) -> tuple[int, int]:
    """Where a new or re-pitched note is played: on `string` if given, else the fingering
    model's choice among the strings not already used at that moment."""
    key = (note.onset_beats, note.pitch)
    if string is not None:
        fret = _fret_for(doc, string, note.pitch)
        if fret is None:
            raise InvalidInputError(f"string {string} can't play that note")
        _free_string(positions, key, string)
        return string, fret
    taken = {s for (onset, _), (s, _) in positions.items() if onset == note.onset_beats}
    tuning = _tuning(doc)
    choice = assign_tab([note], tuning, _capo(doc)).get(key)
    if choice is not None and choice.string not in taken:
        return choice.string, choice.fret
    for candidate in range(1, len(_open_strings(doc)) + 1):  # the model's pick is taken
        fret = _fret_for(doc, candidate, note.pitch)
        if fret is not None and candidate not in taken:
            return candidate, fret
    raise InvalidInputError("no free string can play that note at that moment")


def _tuning(doc: EditableScore) -> Tuning:
    assert doc.tab is not None
    for name, pitches in TUNINGS.items():
        if list(pitches) == doc.tab.tuning:
            return name
    raise InvalidInputError("this score's tuning can't be edited yet")


# ----------------------------------------------------------------------------------------------


def render(doc: EditableScore, out_dir: Path) -> dict[str, Path]:
    """Write a version's files from its document, as the stages do: score.json, score.musicxml,
    quantized.mid, sync.json and, for guitar, tab.musicxml. Returns name -> path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "score.json": out_dir / "score.json",
        "score.musicxml": out_dir / "score.musicxml",
        "quantized.mid": out_dir / "quantized.mid",
        "sync.json": out_dir / "sync.json",
    }
    score = doc.score
    files["score.json"].write_text(doc.model_dump_json(indent=1))
    files["score.musicxml"].write_bytes(write_score(score, doc.instrument))
    seconds_per_beat = 60.0 / score.tempo_bpm
    write_notes(
        files["quantized.mid"],
        [
            (
                float(n.onset_beats) * seconds_per_beat,
                float(n.onset_beats + n.duration_beats) * seconds_per_beat,
                n.pitch,
                n.velocity,
            )
            for n in score.notes
        ],
        program=GM_PROGRAM[doc.instrument],
        tempo_bpm=score.tempo_bpm,
    )
    files["sync.json"].write_text(
        json.dumps({"bar_starts_ms": bar_starts_ms(score, doc.trim_start_s)}) + "\n"
    )
    if doc.tab is not None:
        layout = TabLayout(
            tuning=tuple(doc.tab.tuning),
            capo=doc.tab.capo,
            positions={(t.onset_beats, t.pitch): (t.string, t.fret) for t in doc.tab.notes},
        )
        files["tab.musicxml"] = out_dir / "tab.musicxml"
        files["tab.musicxml"].write_bytes(write_score(score, doc.instrument, tab=layout))
    return files
