"""Export the GAPS guitar model to ONNX and record upstream outputs for the parity tests (ADR-0014).

Runs in a throwaway env with the real packages, NOT in this project's env, e.g.:
    uv venv /tmp/gaps --python 3.12
    uv pip install -p /tmp/gaps torch==2.14.1 onnx==1.23.2 onnxruntime==1.30.0 \
        hf-midi-transcription==0.1.1 librosa==1.0.0 soundfile
    /tmp/gaps/bin/python packages/pipeline/tests/fixtures/gaps/make_reference.py model
    /tmp/gaps/bin/python packages/pipeline/tests/fixtures/gaps/make_reference.py reference

`model` writes `pipeline/models/gaps/guitar.onnx`: the `guitar-gaps-paper-version-12200_iterations`
checkpoint (99 MB) as a 33 MB ONNX graph from log-mel frames to the four note outputs, taking any
number of frames; see `export_model` for each step. Its int8 convolutions are calibrated on the
GuitarSet tuning clips (`tests/tuning/make_tuning_set.py`), none of which are test clips.

`reference` writes `reference.npz` for one 12 s GuitarSet clip (two 10 s chunks): upstream's
log-mel spectrogram, its float32 PyTorch outputs, and the notes upstream's post-processor
decodes from them.
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile
from scipy.signal import resample_poly

HERE = Path(__file__).parent
MODEL_DIR = HERE.parents[2] / "src" / "pipeline" / "models" / "gaps"
TUNING = Path.home() / ".cache" / "tabscribe" / "guitarset-tuning"
REPO_ID = "xavriley/midi-transcription-models"
REVISION = "b7bec65a2b860aca72856b0feef58b5df407b777"
CHECKPOINT = "guitar-gaps-paper-version-12200_iterations.pth"
CLIP = HERE.parent / "guitarset" / "05_BN1-129-Eb_solo.flac"
OUTPUTS = ["onset", "offset", "frame", "velocity"]


def load(path: Path, seconds: float | None = None) -> np.ndarray:
    """Mono float32 at 16 kHz, resampled the way the transcribe stage does it (from 44.1 kHz)."""
    audio, rate = soundfile.read(path, dtype="float32")
    assert rate == 44_100, rate
    audio = np.asarray(resample_poly(audio, 160, 441), np.float32)
    return audio if seconds is None else audio[: int(seconds * 16_000)]


def upstream() -> Any:
    from huggingface_hub import hf_hub_download
    from piano_transcription_inference import PianoTranscription

    path = hf_hub_download(REPO_ID, CHECKPOINT, revision=REVISION)
    model = PianoTranscription(
        "Regress_onset_offset_frame_velocity_CRNN", device="cpu", checkpoint_path=path
    ).model
    return model.eval()


def body(torch: Any, model: Any) -> Any:
    """The model after its log-mel extractor (ported to numpy in `pipeline/gaps.py`)."""

    class Body(torch.nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.m = model

        def forward(self, mel: Any) -> Any:  # (batch, 1, frames, 229)
            m = self.m
            x = m.bn0(mel.transpose(1, 3)).transpose(1, 3)
            frame, onset = m.frame_model(x), m.reg_onset_model(x)
            offset, velocity = m.reg_offset_model(x), m.velocity_model(x)
            y, _ = m.reg_onset_gru(torch.cat((onset, (onset**0.5) * velocity), dim=2))
            onset = torch.sigmoid(m.reg_onset_fc(y))
            y, _ = m.frame_gru(torch.cat((frame, onset, offset), dim=2))
            frame = torch.sigmoid(m.frame_fc(y))
            return onset, offset, frame, velocity

    return Body().eval()


def upstream_log_mel(torch: Any, model: Any, audio: np.ndarray) -> np.ndarray:
    with torch.no_grad():
        spect = model.spectrogram_extractor(torch.from_numpy(audio[None]))
        return np.asarray(model.logmel_extractor(spect)[0, 0].numpy())  # (frames, 229)


def export_model() -> None:
    """Export, quantize, shrink; each step checked to keep note F1 (`make test-accuracy`) and to
    shrink the file or the time per chunk (staging VM, 2 vCPU EPYC)."""
    import importlib
    import tempfile

    import onnx
    from onnx import TensorProto, helper, numpy_helper
    from onnxruntime.quantization import (
        CalibrationDataReader,
        CalibrationMethod,
        QuantFormat,
        QuantType,
        quantize_dynamic,
        quantize_static,
    )
    from onnxruntime.quantization.shape_inference import quant_pre_process

    # Untyped on purpose: torch is only installed in the throwaway env (and with the optional
    # separation extra), so mypy must see the same thing with or without it.
    torch: Any = importlib.import_module("torch")
    model = upstream()
    calibration = sorted(TUNING.glob("*.flac"))[::6]  # 9 clips, comp and solo

    class Reader(CalibrationDataReader):  # type: ignore[misc]
        def __init__(self) -> None:
            chunks = []
            for path in calibration:
                mel = upstream_log_mel(torch, model, load(path))
                chunks += [mel[s : s + 1000] for s in range(0, len(mel) - 1000, 1000)][:2]
            self._chunks = iter(chunks)

        def get_next(self) -> dict[str, np.ndarray] | None:
            chunk = next(self._chunks, None)
            return None if chunk is None else {"mel": chunk[None, None]}

    with tempfile.TemporaryDirectory() as tmp:
        exported, prepared = Path(tmp, "float.onnx"), Path(tmp, "pre.onnx")
        convs, matmuls = Path(tmp, "conv.onnx"), Path(tmp, "matmul.onnx")
        torch.onnx.export(
            body(torch, model),
            (torch.zeros(1, 1, 1000, 229),),
            str(exported),
            dynamo=False,  # matches the Beat This! export (torch 2.14.1)
            opset_version=17,
            input_names=["mel"],
            output_names=OUTPUTS,
            dynamic_axes={"mel": {0: "batch", 2: "frames"}}
            | {name: {0: "batch", 1: "frames"} for name in OUTPUTS},
        )
        quant_pre_process(str(exported), str(prepared), skip_symbolic_shape=True)
        # int8 convolutions (most of the compute): 3.1 -> 1.9 s per 30 s on the staging VM, F1
        # unchanged. Each model's first convolution (one input channel, cheap) stays float, and
        # so does everything after the convolutions: int8 outputs give the onset curves flat
        # steps that the peak picker reads as extra notes (precision 0.97 -> 0.83).
        nodes = [n.name for n in onnx.load(str(prepared)).graph.node if n.op_type == "Conv"]
        quantize_static(
            prepared,
            convs,
            Reader(),
            quant_format=QuantFormat.QDQ,
            op_types_to_quantize=["Conv"],
            nodes_to_quantize=[n for n in nodes if "conv_block1/conv1" not in n],
            per_channel=True,
            activation_type=QuantType.QUInt8,
            weight_type=QuantType.QInt8,
            calibrate_method=CalibrationMethod.Percentile,
            extra_options={"CalibPercentile": 99.99},
        )
        # int8 weights for the fully connected layers (activations stay float): 75 -> 58 MB.
        quantize_dynamic(
            convs, matmuls, op_types_to_quantize=["MatMul"], weight_type=QuantType.QInt8
        )
        graph = onnx.load(str(matmuls))
    # The GRU weights stored as float16, cast back to float32 when the model loads: 58 -> 33 MB,
    # outputs within 1e-3. (ONNX Runtime's CPU GRU only computes in float32.)
    casts = []
    for tensor in graph.graph.initializer:
        if tensor.data_type == TensorProto.FLOAT and np.prod(tensor.dims) > 4096:
            name = tensor.name
            half = numpy_helper.to_array(tensor).astype(np.float16)
            tensor.CopyFrom(numpy_helper.from_array(half, name + "_f16"))
            casts.append(helper.make_node("Cast", [name + "_f16"], [name], to=TensorProto.FLOAT))
    nodes = casts + list(graph.graph.node)
    del graph.graph.node[:]
    graph.graph.node.extend(nodes)
    _shorten_names(graph.graph)
    onnx.save(graph, str(MODEL_DIR / "guitar.onnx"))


def _shorten_names(graph: Any) -> None:
    keep = {v.name for v in graph.input} | {v.name for v in graph.output}
    names: dict[str, str] = {}

    def short(name: str) -> str:
        return name if not name or name in keep else names.setdefault(name, f"t{len(names):x}")

    for tensor in graph.initializer:
        tensor.name = short(tensor.name)
    for node in graph.node:
        node.name = ""
        node.input[:] = [short(n) for n in node.input]
        node.output[:] = [short(n) for n in node.output]
    del graph.value_info[:]


def record_reference() -> None:
    import importlib

    from piano_transcription_inference.utilities import RegressionPostProcessor

    torch: Any = importlib.import_module("torch")
    model = upstream()
    audio = load(CLIP, seconds=12)
    mel = upstream_log_mel(torch, model, audio)
    with torch.no_grad():
        outputs = [o[0].numpy() for o in body(torch, model)(torch.from_numpy(mel[None, None]))]
    post = RegressionPostProcessor(
        100,
        classes_num=88,
        onset_threshold=0.3,
        offset_threshold=0.3,
        frame_threshold=0.1,
        pedal_offset_threshold=0.2,
    )
    events, _ = post.output_dict_to_midi_events(
        {
            f"{'reg_' if n in ('onset', 'offset') else ''}{n}_output": o.copy()
            for n, o in zip(OUTPUTS, outputs, strict=True)
        }
    )
    notes = np.array(
        [[e["onset_time"], e["offset_time"], e["midi_note"], e["velocity"]] for e in events],
        np.float64,
    )
    np.savez_compressed(
        HERE / "reference.npz",
        mel=mel.astype(np.float16),  # float16 keeps it within 0.07 dB
        **{n: o.astype(np.float32) for n, o in zip(OUTPUTS, outputs, strict=True)},
        notes=notes,
    )
    print(f"{len(audio) / 16_000:.0f} s, {len(notes)} notes")


if __name__ == "__main__":
    {"model": export_model, "reference": record_reference}[sys.argv[1]]()
