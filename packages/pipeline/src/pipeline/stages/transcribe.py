"""transcribe: Basic Pitch on the normalized audio -> note events (notes.json) and raw.mid."""

from dataclasses import replace

import numpy as np
import soundfile
from pydantic import Field
from scipy.signal import resample_poly

from pipeline.basic_pitch import (
    ENVELOPE_FPS,
    BasicPitch,
    DecodeParams,
    RawNote,
    decode_notes,
    level_gain,
    onset_envelope,
)
from pipeline.basic_pitch import SAMPLE_RATE as MODEL_RATE
from pipeline.config import Instrument
from pipeline.midi import write_notes
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.separate import SeparatedAudio
from pipeline.types import ArtifactRef, Frozen, StageName, StageOutput

# Playable range per instrument, so the model can't report impossible notes.
PITCH_RANGE = {
    Instrument.GUITAR: (38, 88),  # D2 (drop-D low string) to E6 (24th fret, high E)
    Instrument.PIANO: (21, 108),  # A0 to C8
}
GM_PROGRAM = {Instrument.GUITAR: 25, Instrument.PIANO: 0}  # steel guitar, grand piano
# Note decoding per instrument. Guitar: activations are first scaled to a reference level
# (`level_gain`, so thresholds are relative to the recording), then decoded with settings
# grid-searched on 24 GuitarSet excerpts and checked on the 6 held-out test clips
# (tests/tuning/tune_decoding.py): note F1 0.761 -> 0.818, precision 0.729 -> 0.805, recall
# 0.811 -> 0.844. Fixed thresholds scored nearly as well on GuitarSet but dropped 61 % of the
# notes on a quieter phone recording; relative ones removed ~7 % (mostly stacked extras).
# Piano keeps Basic Pitch's defaults until there is real piano data to tune on (TD-16).
DECODE = {
    Instrument.GUITAR: DecodeParams(
        onset_threshold=0.65, frame_threshold=0.45, min_note_frames=6, infer_onsets=False
    ),
    Instrument.PIANO: DecodeParams(),
}
LEVEL_NORMALIZE = {Instrument.GUITAR: True, Instrument.PIANO: False}


class Note(Frozen):
    onset_s: float = Field(ge=0)
    offset_s: float = Field(ge=0)
    pitch: int = Field(ge=0, le=127)
    velocity: int = Field(ge=1, le=127)
    amplitude: float  # model confidence-like activation, 0..1


class NoteList(Frozen):
    """Contents of notes.json. Times are relative to the normalized audio."""

    notes: list[Note]


class NoteEvents(StageOutput):
    stage = StageName.TRANSCRIBE
    notes: ArtifactRef  # notes.json (NoteList)
    midi: ArtifactRef  # raw.mid, unquantized, fixed 120 bpm grid
    onset_envelope: ArtifactRef  # onset_envelope.npy, float32, for beat tracking
    envelope_fps: float
    # frames.npy: float16 (n_frames, 88) raw note activations for chord recognition; bin 0 is
    # A0, frame i is at basic_pitch.frame_times(n_frames)[i]
    frames: ArtifactRef
    note_count: int


class TranscribeStage(Stage[NoteEvents]):
    name = StageName.TRANSCRIBE
    # 2: note decoding moved to Rust; 3: onset envelope output; 4: reads the separate stage;
    # 5-6: tuned guitar decoding, relative to the recording's level; 7: frames output
    version = "7"
    requires = (NormalizedAudio, SeparatedAudio)
    output_type = NoteEvents

    def __init__(self) -> None:
        self._model: BasicPitch | None = None  # loaded on first run, not when cached

    def run(self, inputs: StageInputs, ctx: StageContext) -> NoteEvents:
        source = inputs.get(SeparatedAudio).audio or inputs.get(NormalizedAudio).audio
        audio, rate = soundfile.read(inputs.path(source), dtype="float32")
        if rate % MODEL_RATE:
            raise ValueError(f"expected a multiple of {MODEL_RATE} Hz, got {rate} Hz")
        audio = resample_poly(audio, 1, rate // MODEL_RATE).astype(np.float32)

        if self._model is None:
            self._model = BasicPitch()
        low, high = PITCH_RANGE[ctx.cfg.instrument]
        frames, onsets = self._model.activations(audio)
        params = replace(DECODE[ctx.cfg.instrument], min_pitch=low, max_pitch=high)
        gain = level_gain(frames, low, high) if LEVEL_NORMALIZE[ctx.cfg.instrument] else 1.0
        raw = [  # velocities stay on the recording's own scale
            replace(n, amplitude=n.amplitude / gain)
            for n in decode_notes(frames * gain, onsets * gain, params)
        ]
        np.save(ctx.path("onset_envelope.npy"), onset_envelope(onsets, low, high))
        np.save(ctx.path("frames.npy"), frames.astype(np.float16))
        notes = [_to_note(n) for n in raw]

        ctx.path("notes.json").write_text(NoteList(notes=notes).model_dump_json(indent=1))
        write_notes(
            ctx.path("raw.mid"),
            [(n.onset_s, n.offset_s, n.pitch, n.velocity) for n in notes],
            program=GM_PROGRAM[ctx.cfg.instrument],
        )
        return NoteEvents(
            notes=ctx.ref("notes.json"),
            midi=ctx.ref("raw.mid"),
            onset_envelope=ctx.ref("onset_envelope.npy"),
            envelope_fps=ENVELOPE_FPS,
            frames=ctx.ref("frames.npy"),
            note_count=len(notes),
        )


def _to_note(raw: RawNote) -> Note:
    return Note(
        onset_s=round(max(0.0, raw.start_s), 4),
        offset_s=round(max(0.0, raw.end_s), 4),
        pitch=raw.pitch,
        velocity=min(127, max(1, round(127 * raw.amplitude))),
        amplitude=round(raw.amplitude, 4),
    )
