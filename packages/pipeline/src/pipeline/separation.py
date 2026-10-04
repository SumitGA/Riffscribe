"""Optional source separation with Demucs (`htdemucs_6s`), from the `separation` install extra.

Off by default (ADR-0004, TD-1): on solo recordings it can do more harm than good, it needs
torch (~630 MB installed, ~1.9 GB peak memory) and takes ~2 minutes per 5 minutes of audio on
CPU. Imports are lazy so the core pipeline never loads torch.
"""

from typing import Any

import numpy as np
import numpy.typing as npt

from pipeline.config import Instrument

MODEL = "htdemucs_6s"  # the Demucs model with separate guitar and piano stems
STEM = {Instrument.GUITAR: "guitar", Instrument.PIANO: "piano"}
SAMPLE_RATE = 44_100

_separator: Any = None  # loaded once per process; model load takes seconds


def isolate(audio: npt.NDArray[np.float32], instrument: Instrument) -> npt.NDArray[np.float32]:
    """The instrument's stem from mono 44.1 kHz audio, as mono 44.1 kHz audio."""
    global _separator
    try:
        import torch
        from demucs.api import Separator
    except ImportError as exc:
        raise RuntimeError(
            "source separation needs the optional Demucs install: "
            "`uv sync --group separation` (see docs/tech-debt TD-1)"
        ) from exc
    if _separator is None:
        _separator = Separator(model=MODEL, device="cpu")
    stereo = torch.from_numpy(np.stack([audio, audio]))  # the model expects two channels
    _, stems = _separator.separate_tensor(stereo, SAMPLE_RATE)
    return np.asarray(stems[STEM[instrument]].mean(dim=0).numpy(), dtype=np.float32)
