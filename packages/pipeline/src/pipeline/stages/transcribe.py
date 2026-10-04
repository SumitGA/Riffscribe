"""transcribe: Basic Pitch on the normalized audio -> note events (notes.json) and raw.mid."""

import numpy as np
import soundfile
from pydantic import Field
from scipy.signal import resample_poly

from pipeline.basic_pitch import SAMPLE_RATE as MODEL_RATE
from pipeline.basic_pitch import BasicPitch, DecodeParams, RawNote, decode_notes
from pipeline.config import Instrument
from pipeline.midi import write_notes
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.normalize import NormalizedAudio
from pipeline.types import ArtifactRef, Frozen, StageName, StageOutput

# Playable range per instrument, so the model can't report impossible notes.
PITCH_RANGE = {
    Instrument.GUITAR: (38, 88),  # D2 (drop-D low string) to E6 (24th fret, high E)
    Instrument.PIANO: (21, 108),  # A0 to C8
}
GM_PROGRAM = {Instrument.GUITAR: 25, Instrument.PIANO: 0}  # steel guitar, grand piano


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
    note_count: int


class TranscribeStage(Stage[NoteEvents]):
    name = StageName.TRANSCRIBE
    version = "1"
    requires = (NormalizedAudio,)
    output_type = NoteEvents

    def __init__(self) -> None:
        self._model: BasicPitch | None = None  # loaded on first run, not when cached

    def run(self, inputs: StageInputs, ctx: StageContext) -> NoteEvents:
        normalized = inputs.get(NormalizedAudio)
        audio, rate = soundfile.read(inputs.path(normalized.audio), dtype="float32")
        if rate % MODEL_RATE:
            raise ValueError(f"expected a multiple of {MODEL_RATE} Hz, got {rate} Hz")
        audio = resample_poly(audio, 1, rate // MODEL_RATE).astype(np.float32)

        if self._model is None:
            self._model = BasicPitch()
        low, high = PITCH_RANGE[ctx.cfg.instrument]
        raw = decode_notes(
            *self._model.activations(audio), DecodeParams(min_pitch=low, max_pitch=high)
        )
        notes = [_to_note(n) for n in raw]

        ctx.path("notes.json").write_text(NoteList(notes=notes).model_dump_json(indent=1))
        write_notes(
            ctx.path("raw.mid"),
            [(n.onset_s, n.offset_s, n.pitch, n.velocity) for n in notes],
            program=GM_PROGRAM[ctx.cfg.instrument],
        )
        return NoteEvents(
            notes=ctx.ref("notes.json"), midi=ctx.ref("raw.mid"), note_count=len(notes)
        )


def _to_note(raw: RawNote) -> Note:
    return Note(
        onset_s=round(max(0.0, raw.start_s), 4),
        offset_s=round(max(0.0, raw.end_s), 4),
        pitch=raw.pitch,
        velocity=min(127, max(1, round(127 * raw.amplitude))),
        amplitude=round(raw.amplitude, 4),
    )
