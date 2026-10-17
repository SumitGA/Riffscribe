"""quantize: beat grid, snapping notes to a rhythmic grid and chord names.

Writes quantized.json (the Score) and quantized.mid.
"""

from collections.abc import Sequence
from fractions import Fraction

import numpy as np
import numpy.typing as npt

from pipeline.basic_pitch import frame_times
from pipeline.beats import beat_track
from pipeline.chords import ChordSpan, recognize_chords
from pipeline.midi import write_notes
from pipeline.rhythm import (
    BEATS_PER_BAR,
    StrumParams,
    TimedNote,
    beat_frames_to_times,
    estimate_key,
    quantize,
    tempo_from_beats,
)
from pipeline.score import ChordSymbol, KeySignature, Score, ScoreNote, Strum
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.transcribe import GM_PROGRAM, Note, NoteEvents, NoteList
from pipeline.types import ArtifactRef, StageName, StageOutput

FALLBACK_BPM = 120.0  # when too few beats are found (e.g. one long chord)
# The model hears no beat in some recordings (e.g. single chords with pauses between); then the
# onset-envelope tracker is used. No frame this likely to be a beat = no beat heard.
MIN_BEAT_PROBABILITY = 0.5
STRUM = StrumParams()  # tuned by tests/tuning/tune_strums.py


class QuantizedScore(StageOutput):
    stage = StageName.QUANTIZE
    score: ArtifactRef  # quantized.json (Score)
    midi: ArtifactRef  # quantized.mid at the detected tempo
    tempo_bpm: float
    note_count: int


class QuantizeStage(Stage[QuantizedScore]):
    name = StageName.QUANTIZE
    # 2: simplest grid that fits (quarters, eighths) before sixteenths; 3: strums as chords;
    # 4: chord names; 5: whole strums (StrumParams) with their direction; 6: beats tracked over
    # Beat This! beat probabilities, bars from its downbeat probabilities; 7: strums retuned for
    # GAPS notes
    version = "7"
    requires = (NoteEvents,)
    output_type = QuantizedScore

    def run(self, inputs: StageInputs, ctx: StageContext) -> QuantizedScore:
        events = inputs.get(NoteEvents)
        notes = NoteList.model_validate_json(inputs.path(events.notes).read_text()).notes
        beat_times, downbeat_weights = beat_grid(
            np.load(inputs.path(events.beat_activation)).astype(np.float64),
            events.beat_fps,
            np.load(inputs.path(events.onset_envelope)).astype(np.float64),
            events.envelope_fps,
            notes,
        )
        tempo = round(tempo_from_beats(beat_times), 2)

        rhythm = quantize(
            [TimedNote(n.onset_s, n.offset_s, n.pitch, n.velocity) for n in notes],
            beat_times,
            STRUM,
            downbeat_weights,
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
            strums=[Strum(onset_beats=s.onset_beats, direction=s.direction) for s in rhythm.strums],
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


def beat_grid(
    activation: npt.NDArray[np.float64],
    beat_fps: float,
    envelope: npt.NDArray[np.float64],
    envelope_fps: float,
    notes: Sequence[Note],
) -> tuple[list[float], list[float]]:
    """Beat times, tracked over the beat probabilities (the onset envelope when no beat is
    heard), and each beat's downbeat probability (empty from the envelope)."""
    if activation.size and activation[:, 0].max() >= MIN_BEAT_PROBABILITY:
        beat_frames = beat_track(activation[:, 0], beat_fps)[1]
        if beat_frames.size >= 2:
            beat_times = beat_frames_to_times(beat_frames, beat_fps)
            return beat_times, activation[beat_frames, 1].tolist()
    return track_beats(envelope, envelope_fps, notes), []


def track_beats(
    envelope: npt.NDArray[np.float64], fps: float, notes: Sequence[Note]
) -> list[float]:
    """Beat times from the onset envelope; a fallback grid if the tracker finds fewer than two."""
    _, frames = beat_track(envelope, fps)
    beat_times = beat_frames_to_times(frames, fps)
    if len(beat_times) < 2:
        start = min((n.onset_s for n in notes), default=0.0)
        beat_times = [start + i * 60.0 / FALLBACK_BPM for i in range(2)]
    return beat_times


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
