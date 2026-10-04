"""MusicXML 4.0 writer for quantized scores: deterministic bytes, no dependencies.

Scope (v1, see docs/tech-debt TD-14): one voice per staff (notes sharing an onset form a chord,
cut short where the next chord starts), 4/4 with an optional pickup bar, sixteenth and
eighth-triplet grids, ties across bar lines and beats, guitar on a treble-8vb staff, piano on a
grand staff split at middle C. With a TabLayout, guitar gets a second, 6-line TAB staff with
string/fret numbers (the layout MuseScore and Guitar Pro use). No beaming hints; renderers beam
automatically.
"""

import math
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from itertools import pairwise

from pipeline.config import Instrument
from pipeline.score import Score, ScoreNote

DIVISIONS = 12  # per quarter note: multiples of both 1/4 (sixteenths) and 1/3 (triplets)
PIANO_SPLIT = 60  # middle C and above on the treble staff
GM_PROGRAM_1_BASED = {Instrument.GUITAR: 26, Instrument.PIANO: 1}  # MusicXML counts from 1

_SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# Note value per length in twelfths of a beat: (type, dots).
_STRAIGHT = {
    3: ("16th", 0),
    6: ("eighth", 0),
    9: ("eighth", 1),
    12: ("quarter", 0),
    18: ("quarter", 1),
    24: ("half", 0),
    36: ("half", 1),
    48: ("whole", 0),
}
_TRIPLET = {4: ("eighth", 0), 8: ("quarter", 0)}
_WHOLE_BEATS = (48, 36, 24, 12)  # longest first, for splitting whole-beat spans


@dataclass(frozen=True)
class Event:
    """A chord (or a rest when `pitches` is empty) over [start, end) in beats."""

    start: Fraction
    end: Fraction
    pitches: tuple[int, ...]
    technical: tuple[tuple[int, int], ...] = ()  # (string, fret) per pitch on a TAB staff


@dataclass(frozen=True)
class Piece:
    """One written note/rest: a slice of an event that fits a single note value."""

    start: Fraction
    length: Fraction
    pitches: tuple[int, ...]
    tie_start: bool
    tie_stop: bool
    technical: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True)
class TabLayout:
    """Guitar tab: open-string pitches (lowest first, no capo), capo and note positions."""

    tuning: tuple[int, ...]
    capo: int
    # (onset_beats, pitch) -> (string number, 1 = highest string; fret relative to the capo)
    positions: Mapping[tuple[Fraction, int], tuple[int, int]]


def write_score(
    score: Score,
    instrument: Instrument,
    title: str = "Transcription",
    tab: TabLayout | None = None,
) -> bytes:
    staves = _staff_notes(score.notes, instrument, tab)
    bars = _bar_lines(score, staves)
    root = ET.Element("score-partwise", version="4.0")
    ET.SubElement(ET.SubElement(root, "work"), "work-title").text = title
    encoding = ET.SubElement(ET.SubElement(root, "identification"), "encoding")
    ET.SubElement(encoding, "software").text = "TabScribe"
    _part_list(root, instrument)

    part = ET.SubElement(root, "part", id="P1")
    positions: list[Mapping[tuple[Fraction, int], tuple[int, int]] | None] = [None] * len(staves)
    if tab is not None:
        positions[-1] = tab.positions  # the TAB staff is the last one
    events = [
        _regrid(_events(notes, bars[-1], staff_positions))
        for notes, staff_positions in zip(staves, positions, strict=True)
    ]
    for index, (bar_start, bar_end) in enumerate(pairwise(bars)):
        number = str(index if score.pickup_beats > 0 else index + 1)
        measure = ET.SubElement(part, "measure", number=number)
        if index == 0 and score.pickup_beats > 0:
            measure.set("implicit", "yes")
        if index == 0:
            _attributes(measure, score, instrument, len(staves), tab)
            _tempo(measure, score.tempo_bpm)
        for staff, staff_events in enumerate(events, start=1):
            if staff > 1:
                backup = ET.SubElement(measure, "backup")
                ET.SubElement(backup, "duration").text = _divisions(bar_end - bar_start)
            pieces = _pieces(staff_events, bar_start, bar_end)
            _write_pieces(
                measure, pieces, staff, len(staves), bar_end - bar_start, score.key.fifths
            )

    ET.indent(root, space="  ")
    header = (
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n'
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 4.0 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">\n'
    )
    return header.encode() + ET.tostring(root, encoding="unicode").encode() + b"\n"


def _staff_notes(
    notes: Sequence[ScoreNote], instrument: Instrument, tab: TabLayout | None
) -> list[list[ScoreNote]]:
    if tab is not None:
        # Notation staff with every note; TAB staff with the notes that have a position.
        return [list(notes), [n for n in notes if (n.onset_beats, n.pitch) in tab.positions]]
    if instrument is Instrument.PIANO:
        return [
            [n for n in notes if n.pitch >= PIANO_SPLIT],
            [n for n in notes if n.pitch < PIANO_SPLIT],
        ]
    return [list(notes)]


def _bar_lines(score: Score, staves: Sequence[Sequence[ScoreNote]]) -> list[Fraction]:
    """Bar start positions in beats, plus the end of the last bar."""
    end = max((n.onset_beats + n.duration_beats for s in staves for n in s), default=Fraction(0))
    bars = [Fraction(0), Fraction(score.pickup_beats or score.beats_per_bar)]
    while bars[-1] < end:
        bars.append(bars[-1] + score.beats_per_bar)
    return bars


def _events(
    notes: Sequence[ScoreNote],
    score_end: Fraction,
    positions: Mapping[tuple[Fraction, int], tuple[int, int]] | None = None,
) -> list[Event]:
    """One voice: chords at each onset, each lasting until it ends or the next one starts."""
    by_onset: dict[Fraction, list[ScoreNote]] = {}
    for n in notes:
        by_onset.setdefault(n.onset_beats, []).append(n)
    onsets = sorted(by_onset)
    events, cursor = [], Fraction(0)
    for i, onset in enumerate(onsets):
        if onset > cursor:
            events.append(Event(cursor, onset, ()))
        end = max(n.onset_beats + n.duration_beats for n in by_onset[onset])
        if i + 1 < len(onsets):
            end = min(end, onsets[i + 1])
        pitches = tuple(sorted({n.pitch for n in by_onset[onset]}))
        technical = tuple(positions[(onset, p)] for p in pitches) if positions else ()
        events.append(Event(onset, end, pitches, technical))
        cursor = end
    if cursor < score_end:
        events.append(Event(cursor, score_end, ()))
    return events


def _regrid(events: Sequence[Event]) -> list[Event]:
    """Give every beat a single grid so each span inside it has a note value.

    quantize already picks one grid per beat, but edited scores may mix sixteenths and triplets
    inside a beat (e.g. 1/4 to 2/3, which only a sextuplet could write). A beat keeps triplets
    only if all its boundaries are on thirds; otherwise they snap to the nearest sixteenth.
    Events that shrink to nothing are dropped.
    """
    points = {e.start for e in events} | {e.end for e in events}
    by_beat: dict[int, list[Fraction]] = {}
    for p in points:
        if p.denominator != 1:
            by_beat.setdefault(math.floor(p), []).append(p)
    snapped = {p: p for p in points}
    for beat, beat_points in by_beat.items():
        divisions = 3 if all((p * 3).denominator == 1 for p in beat_points) else 4
        for p in beat_points:
            snapped[p] = beat + Fraction(round((p - beat) * divisions), divisions)
    regridded = (Event(snapped[e.start], snapped[e.end], e.pitches, e.technical) for e in events)
    return [e for e in regridded if e.start < e.end]


def _pieces(events: Iterable[Event], bar_start: Fraction, bar_end: Fraction) -> list[Piece]:
    """Slices of the events inside one bar, each a single writable note value."""
    pieces: list[Piece] = []
    for event in events:
        start, end = max(event.start, bar_start), min(event.end, bar_end)
        if start >= end:
            continue
        for s, e in _split(start, end):
            sounding = bool(event.pitches)
            pieces.append(
                Piece(
                    start=s,
                    length=e - s,
                    pitches=event.pitches,
                    tie_start=sounding and e < event.end,
                    tie_stop=sounding and s > event.start,
                    technical=event.technical,
                )
            )
    return pieces


def _split(start: Fraction, end: Fraction) -> list[tuple[Fraction, Fraction]]:
    """Cut [start, end) into spans that each have a note value."""
    if start.denominator == 1 and end.denominator == 1:
        return _whole_beat_spans(start, end)
    spans: list[tuple[Fraction, Fraction]] = []
    cursor = start
    while cursor < end:
        if cursor.denominator == 1 and end >= cursor + 1:
            whole_end = Fraction(math.floor(end))  # whole beats inside a syncopated span
            spans.extend(_whole_beat_spans(cursor, whole_end))
            cursor = whole_end
            continue
        stop = min(end, Fraction(math.floor(cursor) + 1))
        spans.extend(_within_beat_spans(cursor, stop))
        cursor = stop
    return spans


def _whole_beat_spans(start: Fraction, end: Fraction) -> list[tuple[Fraction, Fraction]]:
    spans, cursor = [], start
    while cursor < end:
        remaining = int((end - cursor) * 12)
        length = Fraction(next(n for n in _WHOLE_BEATS if n <= remaining), 12)
        spans.append((cursor, cursor + length))
        cursor += length
    return spans


def _within_beat_spans(start: Fraction, end: Fraction) -> list[tuple[Fraction, Fraction]]:
    """A span inside one beat; lengths without a single note value are split further."""
    table = _TRIPLET if _on_triplet_grid(start, end - start) else _STRAIGHT
    twelfths = int((end - start) * 12)
    if twelfths in table:
        return [(start, end)]
    units = sorted((n for n in table if n < 12), reverse=True)
    spans, cursor = [], start
    while twelfths:
        unit = next((n for n in units if n <= twelfths), None)
        if unit is None:
            raise ValueError(f"cannot notate span {start}..{end}")
        spans.append((cursor, cursor + Fraction(unit, 12)))
        cursor += Fraction(unit, 12)
        twelfths -= unit
    return spans


def _on_triplet_grid(start: Fraction, length: Fraction) -> bool:
    return (start * 3).denominator == 1 and (length * 3).denominator == 1 and length < 1


def _write_pieces(
    measure: ET.Element,
    pieces: Sequence[Piece],
    staff: int,
    n_staves: int,
    bar_length: Fraction,
    fifths: int,
) -> None:
    triplet_beats = {
        math.floor(p.start)
        for p in pieces
        if _on_triplet_grid(p.start, p.length) and int(p.length * 12) in _TRIPLET
    }
    voice = "1" if staff == 1 else "5"
    for i, piece in enumerate(pieces):
        beat = math.floor(piece.start)
        in_triplet = beat in triplet_beats and piece.length < 1
        first_in_group = in_triplet and (i == 0 or math.floor(pieces[i - 1].start) != beat)
        last_in_group = in_triplet and (
            i == len(pieces) - 1 or math.floor(pieces[i + 1].start) != beat
        )
        whole_bar_rest = not piece.pitches and piece.length == bar_length
        for chord_index, pitch in enumerate(piece.pitches or (None,)):
            note = ET.SubElement(measure, "note")
            if chord_index > 0:
                ET.SubElement(note, "chord")
            if pitch is None:
                rest = ET.SubElement(note, "rest")
                if whole_bar_rest:
                    rest.set("measure", "yes")
            else:
                _pitch(note, pitch, fifths)
            ET.SubElement(note, "duration").text = _divisions(piece.length)
            if piece.tie_stop:
                ET.SubElement(note, "tie", type="stop")
            if piece.tie_start:
                ET.SubElement(note, "tie", type="start")
            ET.SubElement(note, "voice").text = voice
            if not whole_bar_rest:
                kind, dots = (_TRIPLET if in_triplet else _STRAIGHT)[int(piece.length * 12)]
                ET.SubElement(note, "type").text = kind
                for _ in range(dots):
                    ET.SubElement(note, "dot")
            if in_triplet:
                modification = ET.SubElement(note, "time-modification")
                ET.SubElement(modification, "actual-notes").text = "3"
                ET.SubElement(modification, "normal-notes").text = "2"
            if n_staves > 1:
                ET.SubElement(note, "staff").text = str(staff)
            notations: list[tuple[str, dict[str, str]]] = []
            if piece.tie_stop:
                notations.append(("tied", {"type": "stop"}))
            if piece.tie_start:
                notations.append(("tied", {"type": "start"}))
            if chord_index == 0 and first_in_group:
                notations.append(("tuplet", {"type": "start", "bracket": "yes"}))
            if chord_index == 0 and last_in_group:
                notations.append(("tuplet", {"type": "stop"}))
            if notations or piece.technical:
                element = ET.SubElement(note, "notations")
                for tag, attrs in notations:
                    ET.SubElement(element, tag, attrs)
                if piece.technical:
                    string, fret = piece.technical[chord_index]
                    technical = ET.SubElement(element, "technical")
                    ET.SubElement(technical, "string").text = str(string)
                    ET.SubElement(technical, "fret").text = str(fret)


def _pitch(note: ET.Element, midi: int, fifths: int) -> None:
    name = (_FLAT_NAMES if fifths < 0 else _SHARP_NAMES)[midi % 12]
    pitch = ET.SubElement(note, "pitch")
    ET.SubElement(pitch, "step").text = name[0]
    if len(name) > 1:
        ET.SubElement(pitch, "alter").text = "1" if name[1] == "#" else "-1"
    ET.SubElement(pitch, "octave").text = str(midi // 12 - 1)


def _attributes(
    measure: ET.Element,
    score: Score,
    instrument: Instrument,
    staves: int,
    tab: TabLayout | None,
) -> None:
    attributes = ET.SubElement(measure, "attributes")
    ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
    key = ET.SubElement(attributes, "key")
    ET.SubElement(key, "fifths").text = str(score.key.fifths)
    ET.SubElement(key, "mode").text = score.key.mode
    time = ET.SubElement(attributes, "time")
    ET.SubElement(time, "beats").text = str(score.beats_per_bar)
    ET.SubElement(time, "beat-type").text = str(score.beat_unit)
    if staves > 1:
        ET.SubElement(attributes, "staves").text = str(staves)
    clefs = [("G", "2", 0), ("F", "4", 0)] if instrument is Instrument.PIANO else [("G", "2", -1)]
    if tab is not None:
        clefs.append(("TAB", "5", 0))
    for number, (sign, line, octave_change) in enumerate(clefs, start=1):
        clef = ET.SubElement(attributes, "clef")
        if staves > 1:
            clef.set("number", str(number))
        ET.SubElement(clef, "sign").text = sign
        ET.SubElement(clef, "line").text = line
        if octave_change:
            # Guitar sounds an octave below written; <pitch> values are the sounding pitches.
            ET.SubElement(clef, "clef-octave-change").text = str(octave_change)

    if tab is not None:
        details = ET.SubElement(attributes, "staff-details", number=str(staves))
        ET.SubElement(details, "staff-lines").text = str(len(tab.tuning))
        for line_number, pitch in enumerate(tab.tuning, start=1):  # line 1 = lowest string
            tuning = ET.SubElement(details, "staff-tuning", line=str(line_number))
            name = _SHARP_NAMES[pitch % 12]
            ET.SubElement(tuning, "tuning-step").text = name[0]
            if len(name) > 1:
                ET.SubElement(tuning, "tuning-alter").text = "1"
            ET.SubElement(tuning, "tuning-octave").text = str(pitch // 12 - 1)
        if tab.capo:
            ET.SubElement(details, "capo").text = str(tab.capo)


def _tempo(measure: ET.Element, bpm: float) -> None:
    direction = ET.SubElement(measure, "direction", placement="above")
    metronome = ET.SubElement(ET.SubElement(direction, "direction-type"), "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = str(round(bpm))
    ET.SubElement(direction, "sound", tempo=f"{bpm:g}")


def _part_list(root: ET.Element, instrument: Instrument) -> None:
    name = "Guitar" if instrument is Instrument.GUITAR else "Piano"
    score_part = ET.SubElement(ET.SubElement(root, "part-list"), "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = name
    score_instrument = ET.SubElement(score_part, "score-instrument", id="P1-I1")
    ET.SubElement(score_instrument, "instrument-name").text = name
    midi = ET.SubElement(score_part, "midi-instrument", id="P1-I1")
    ET.SubElement(midi, "midi-channel").text = "1"
    ET.SubElement(midi, "midi-program").text = str(GM_PROGRAM_1_BASED[instrument])


def _divisions(beats: Fraction) -> str:
    value = beats * DIVISIONS
    if value.denominator != 1:
        raise ValueError(f"{beats} beats is not a whole number of divisions")
    return str(value.numerator)
