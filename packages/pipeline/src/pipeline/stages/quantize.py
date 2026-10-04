"""quantize: beat tracking + snapping notes to a rhythmic grid -> quantized.json and .mid."""

from fractions import Fraction
from typing import Literal

import numpy as np

from pipeline.beats import beat_track
from pipeline.midi import write_notes
from pipeline.rhythm import (
    BEATS_PER_BAR,
    TimedNote,
    beat_frames_to_times,
    estimate_key,
    quantize,
    tempo_from_beats,
)
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.transcribe import GM_PROGRAM, NoteEvents, NoteList
from pipeline.types import ArtifactRef, Frozen, StageName, StageOutput

FALLBACK_BPM = 120.0  # when too few beats are found (e.g. one long chord)


class ScoreNote(Frozen):
    pitch: int
    velocity: int
    onset_beats: Fraction  # from the start of the first (possibly partial) bar
    duration_beats: Fraction
    onset_s: float  # original timing, for playback sync and debugging
    offset_s: float


class KeySignature(Frozen):
    tonic: int  # pitch class, 0 = C
    mode: Literal["major", "minor"]
    fifths: int  # sharps > 0, flats < 0


class Score(Frozen):
    """Contents of quantized.json."""

    tempo_bpm: float
    beats_per_bar: int
    beat_unit: int
    pickup_beats: int
    key: KeySignature
    beat_times_s: list[float]  # time in the normalized audio of beat 0, 1, 2, ...
    notes: list[ScoreNote]


class QuantizedScore(StageOutput):
    stage = StageName.QUANTIZE
    score: ArtifactRef  # quantized.json (Score)
    midi: ArtifactRef  # quantized.mid at the detected tempo
    tempo_bpm: float
    note_count: int


class QuantizeStage(Stage[QuantizedScore]):
    name = StageName.QUANTIZE
    version = "1"
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
