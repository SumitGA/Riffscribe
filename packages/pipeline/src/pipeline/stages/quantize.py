"""quantize: beat tracking, snapping notes to a rhythmic grid and chord names.

Writes quantized.json (the Score) and quantized.mid.
"""

from fractions import Fraction

import numpy as np

from pipeline.basic_pitch import frame_times
from pipeline.beats import beat_track
from pipeline.chords import ChordSpan, recognize_chords
from pipeline.midi import write_notes
from pipeline.rhythm import (
    BEATS_PER_BAR,
    TimedNote,
    beat_frames_to_times,
    estimate_key,
    quantize,
    tempo_from_beats,
)
from pipeline.score import ChordSymbol, KeySignature, Score, ScoreNote
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.transcribe import GM_PROGRAM, NoteEvents, NoteList
from pipeline.types import ArtifactRef, StageName, StageOutput

FALLBACK_BPM = 120.0  # when too few beats are found (e.g. one long chord)


class QuantizedScore(StageOutput):
    stage = StageName.QUANTIZE
    score: ArtifactRef  # quantized.json (Score)
    midi: ArtifactRef  # quantized.mid at the detected tempo
    tempo_bpm: float
    note_count: int


class QuantizeStage(Stage[QuantizedScore]):
    name = StageName.QUANTIZE
    # 2: simplest grid that fits (quarters, eighths) before sixteenths; 3: strums as chords;
    # 4: chord names
    version = "4"
    requires = (NoteEvents,)
    output_type = QuantizedScore

    def run(self, inputs: StageInputs, ctx: StageContext) -> QuantizedScore:
        events = inputs.get(NoteEvents)
        notes = NoteList.model_validate_json(inputs.path(events.notes).read_text()).notes
        envelope = np.load(inputs.path(events.onset_envelope)).astype(np.float64)

        _, frames = beat_track(envelope, events.envelope_fps)
        beat_times = beat_frames_to_times(frames, events.envelope_fps)
        if len(beat_times) < 2:
            start = min((n.onset_s for n in notes), default=0.0)
            beat_times = [start + i * 60.0 / FALLBACK_BPM for i in range(2)]
        tempo = round(tempo_from_beats(beat_times), 2)

        rhythm = quantize(
            [TimedNote(n.onset_s, n.offset_s, n.pitch, n.velocity) for n in notes], beat_times
        )
        key = estimate_key(rhythm.notes)
        frames = np.load(inputs.path(events.frames))
        spans = recognize_chords(frames, frame_times(len(frames)), rhythm.beat_times_s)
        score = Score(
            tempo_bpm=tempo,
            beats_per_bar=BEATS_PER_BAR,
            beat_unit=4,
            pickup_beats=rhythm.pickup_beats,
            key=KeySignature(tonic=key.tonic, mode=key.mode, fifths=key.fifths),
            beat_times_s=rhythm.beat_times_s,
            notes=[
                ScoreNote(
                    pitch=n.pitch,
                    velocity=n.velocity,
                    onset_beats=n.onset_beats,
                    duration_beats=n.duration_beats,
                    onset_s=n.onset_s,
                    offset_s=n.offset_s,
                )
                for n in rhythm.notes
            ],
            chords=chord_symbols(spans),
        )
        ctx.path("quantized.json").write_text(score.model_dump_json(indent=1))

        seconds_per_beat = 60.0 / tempo
        write_notes(
            ctx.path("quantized.mid"),
            [
                (
                    float(n.onset_beats) * seconds_per_beat,
                    float(n.onset_beats + n.duration_beats) * seconds_per_beat,
                    n.pitch,
                    n.velocity,
                )
                for n in rhythm.notes
            ],
            program=GM_PROGRAM[ctx.cfg.instrument],
            tempo_bpm=tempo,
        )
        return QuantizedScore(
            score=ctx.ref("quantized.json"),
            midi=ctx.ref("quantized.mid"),
            tempo_bpm=tempo,
            note_count=len(score.notes),
        )


def chord_symbols(spans: list[list[ChordSpan | None]]) -> list[ChordSymbol]:
    """Per-beat chord spans -> one symbol per run of the same chord (beat 0 = first span)."""
    symbols: list[ChordSymbol] = []
    for beat, parts in enumerate(spans):
        for index, span in enumerate(parts):
            if span is None:
                continue
            onset = beat + Fraction(index, len(parts))
            length = Fraction(1, len(parts))
            last = symbols[-1] if symbols else None
            if (
                last is not None
                and (last.root, last.quality) == (span.root, span.quality)
                and last.onset_beats + last.duration_beats == onset
            ):
                symbols[-1] = last.model_copy(
                    update={
                        "duration_beats": last.duration_beats + length,
                        "offset_s": round(span.end_s, 4),
                    }
                )
            else:
                symbols.append(
                    ChordSymbol(
                        root=span.root,
                        quality=span.quality,
                        onset_beats=onset,
                        duration_beats=length,
                        onset_s=round(span.start_s, 4),
                        offset_s=round(span.end_s, 4),
                    )
                )
    return symbols
