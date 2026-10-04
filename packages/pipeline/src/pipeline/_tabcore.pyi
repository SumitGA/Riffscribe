"""Type stubs for the Rust extension module (see rust/lib.rs)."""

import numpy as np
import numpy.typing as npt

__version__: str

def decode_notes(
    frames: npt.NDArray[np.float32],
    onsets: npt.NDArray[np.float32],
    *,
    onset_threshold: float,
    frame_threshold: float,
    min_note_frames: int,
    min_pitch_bin: int,
    max_pitch_bin: int,
    infer_onsets: bool,
    melodia_trick: bool,
    energy_tolerance: int,
) -> list[tuple[int, int, int, float]]: ...
