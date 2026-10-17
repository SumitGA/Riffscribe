"""transcribe: the normalized audio -> note events (notes.json) and raw.mid, from the GAPS
model for guitar and Basic Pitch for piano; Beat This! on the same audio -> beat and downbeat
probabilities (beat_activation.npy)."""

import math

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
    onset_envelope,
)
from pipeline.basic_pitch import SAMPLE_RATE as MODEL_RATE
from pipeline.beat_this import FPS as BEAT_FPS
from pipeline.beat_this import BeatThis
from pipeline.config import Instrument
from pipeline.gaps import SAMPLE_RATE as GAPS_RATE
from pipeline.gaps import Gaps
from pipeline.gaps import decode_notes as decode_gaps
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
# Guitar notes come from the GAPS model (ADR-0014): on the held-out Guitar-TECHS clips note F1
# 0.78 -> 0.88, a sixth of the extra notes. It replaced Basic Pitch with tuned decoding and two
# rules against its extra notes (TD-34), which find nothing to remove in GAPS's notes. Piano
# notes come from Basic Pitch with its default decoding (TD-16). Basic Pitch still runs for
# every instrument: its activations feed chord recognition and the fallback beat tracker.
GAPS_NOTES = {Instrument.GUITAR: True, Instrument.PIANO: False}


class Note(Frozen):
    onset_s: float = Field(ge=0)
    offset_s: float = Field(ge=0)
    pitch: int = Field(ge=0, le=127)
    velocity: int = Field(ge=1, le=127)
    amplitude: float  # 0..1: GAPS's velocity output, or Basic Pitch's mean activation


class NoteList(Frozen):
    """Contents of notes.json. Times are relative to the normalized audio."""

    notes: list[Note]


class NoteEvents(StageOutput):
    stage = StageName.TRANSCRIBE
    notes: ArtifactRef  # notes.json (NoteList)
    midi: ArtifactRef  # raw.mid, unquantized, fixed 120 bpm grid
    # beat_activation.npy: float16 (n_frames, 2), probability of a beat / a downbeat per frame
    beat_activation: ArtifactRef
    beat_fps: float
    onset_envelope: ArtifactRef  # onset_envelope.npy, float32, fallback beat tracking
    envelope_fps: float
    # frames.npy: float16 (n_frames, 88) raw note activations for chord recognition; bin 0 is
    # A0, frame i is at basic_pitch.frame_times(n_frames)[i]
    frames: ArtifactRef
    note_count: int


class TranscribeStage(Stage[NoteEvents]):
    name = StageName.TRANSCRIBE
    # 2: note decoding moved to Rust; 3: onset envelope output; 4: reads the separate stage;
    # 5-6: tuned guitar decoding, relative to the recording's level; 7: frames output;
    # 8: guitar retriggers merged into the note they continue; 9: guitar sub-octave ghosts;
    # 10: beat activation output (Beat This!); 11: guitar notes from the GAPS model
    version = "11"
    requires = (NormalizedAudio, SeparatedAudio)
    output_type = NoteEvents

    def __init__(self) -> None:
        self._model: BasicPitch | None = None  # loaded on first run, not when cached
        self._beat_model: BeatThis | None = None
        self._gaps: Gaps | None = None

    def run(self, inputs: StageInputs, ctx: StageContext) -> NoteEvents:
        source = inputs.get(SeparatedAudio).audio or inputs.get(NormalizedAudio).audio
        original, rate = soundfile.read(inputs.path(source), dtype="float32")
        if rate % MODEL_RATE:
            raise ValueError(f"expected a multiple of {MODEL_RATE} Hz, got {rate} Hz")
        audio = resample_poly(original, 1, rate // MODEL_RATE).astype(np.float32)

        if self._model is None:
            self._model = BasicPitch()
        low, high = PITCH_RANGE[ctx.cfg.instrument]
        frames, onsets = self._model.activations(audio)
        if GAPS_NOTES[ctx.cfg.instrument]:
            if self._gaps is None:
                self._gaps = Gaps()
            common = math.gcd(rate, GAPS_RATE)
            audio_16k = resample_poly(original, GAPS_RATE // common, rate // common)
            raw = decode_gaps(self._gaps.outputs(audio_16k.astype(np.float32)), low, high)
        else:
            raw = decode_notes(frames, onsets, DecodeParams(min_pitch=low, max_pitch=high))
        if self._beat_model is None:
            self._beat_model = BeatThis()
        beats = self._beat_model.activations(audio)  # also a 22050 Hz model
        np.save(ctx.path("beat_activation.npy"), beats.astype(np.float16))
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
            beat_activation=ctx.ref("beat_activation.npy"),
            beat_fps=BEAT_FPS,
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
