"""Export the Beat This! model to ONNX and record upstream outputs for the parity tests (ADR-0013).

Runs in a throwaway env with the real package, NOT in this project's env, e.g.:
    uv venv /tmp/bt --python 3.12
    uv pip install -p /tmp/bt torch==2.14.1 torchaudio==2.11.0 onnx==1.23.2 onnxruntime==1.30.0 \
        "beat_this @ https://github.com/CPJKU/beat_this/archive/b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c.zip"
    /tmp/bt/bin/python packages/pipeline/tests/fixtures/beat_this/make_reference.py model
    /tmp/bt/bin/python packages/pipeline/tests/fixtures/beat_this/make_reference.py reference

`model` writes `pipeline/models/beat_this/small0.onnx`: the `small0` checkpoint (8.1 MB) as a
3.0 MB ONNX graph taking any number of frames; see `export_model` for each step.

`reference` writes `reference.npz`: for each input, upstream's float32 PyTorch logits, and for
"comp" the log-mel spectrogram. "long" joins three GuitarSet clips (60 s) so the 30 s chunking
is exercised.
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np
import soundfile
from scipy.signal import resample_poly

HERE = Path(__file__).parent
MODEL_DIR = HERE.parents[2] / "src" / "pipeline" / "models" / "beat_this"
GUITARSET = HERE.parent / "guitarset"
INPUTS = {
    "comp": ["04_SS1-100-C#_comp"],
    "long": ["00_BN1-129-Eb_comp", "01_Funk1-114-Ab_solo", "02_Jazz1-130-D_comp"],
}


def load(clips: list[str]) -> np.ndarray:
    """Mono float32 at 22050 Hz, resampled the way the transcribe stage does it."""
    parts = []
    for clip in clips:
        audio, rate = soundfile.read(GUITARSET / f"{clip}.flac", dtype="float32")
        parts.append(resample_poly(audio, 1, rate // 22050).astype(np.float32))
    return np.concatenate(parts)


def export_model() -> None:
    """Export, fuse attention, quantize, optimize, shorten names; each step checked to keep the
    beats (`make test-accuracy`) and to shrink the file or the time per chunk."""
    import importlib
    import tempfile

    import onnx
    import onnxruntime as ort
    from beat_this.inference import load_model
    from beat_this.model import roformer
    from onnxruntime.quantization import QuantType, quantize_dynamic

    # Untyped on purpose: torch is only installed in the throwaway env (and with the optional
    # separation extra), so mypy must see the same thing with or without it.
    torch: Any = importlib.import_module("torch")
    model = load_model("small0")
    # The rotary embedding's position cache would be baked into the graph as a 1 MB constant.
    for module in model.modules():
        if hasattr(module, "cache_if_possible"):
            module.cache_if_possible = False
    # Attention as ONNX Runtime's fused MultiHeadAttention kernel instead of MatMul + Softmax:
    # 547 -> 423 ms per 30 s chunk (float, Apple M-series). Same maths as upstream's
    # scaled_dot_product_attention (default scale, no mask, no dropout at inference).
    roformer.Attend.forward = _fused_attend(torch, torch.nn.functional)

    class Logits(torch.nn.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.model = model

        def forward(self, spect: Any) -> Any:
            out = self.model(spect)
            return out["beat"], out["downbeat"]

    with tempfile.TemporaryDirectory() as tmp:
        exported, quantized = Path(tmp, "float.onnx"), Path(tmp, "int8.onnx")
        torch.onnx.export(
            Logits().eval(),
            (torch.zeros(1, 1500, 128),),
            str(exported),
            dynamo=False,  # the dynamo exporter fails on this model (torch 2.14.1)
            opset_version=17,
            input_names=["spect"],
            output_names=["beat", "downbeat"],
            dynamic_axes={"spect": {1: "frames"}, "beat": {1: "frames"}, "downbeat": {1: "frames"}},
            custom_opsets={"com.microsoft": 1},
        )
        # int8 weights for the matrix multiplies: 9.5 -> 4.5 MB, 423 -> 352 ms per chunk, beat F
        # unchanged. Convolutions stay float (ONNX Runtime's int8 convolution is slower on CPU).
        quantize_dynamic(
            exported, quantized, op_types_to_quantize=["MatMul"], weight_type=QuantType.QInt8
        )
        # Save ONNX Runtime's basic graph optimizations (constant folding, redundant nodes:
        # portable, unlike the hardware-specific levels): 4.5 -> 4.0 MB.
        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.optimized_model_filepath = str(quantized)
        ort.InferenceSession(str(quantized), options, providers=["CPUExecutionProvider"])
        graph = onnx.load(str(quantized))
    # Short tensor names instead of the exporter's module paths: 4.0 -> 3.0 MB.
    _shorten_names(graph.graph)
    onnx.save(graph, str(MODEL_DIR / "small0.onnx"))


def _fused_attend(torch: Any, functional: Any) -> Any:
    def function(heads: int) -> Any:
        class MultiHeadAttention(torch.autograd.Function):  # type: ignore[misc]
            @staticmethod
            def forward(ctx: Any, q: Any, k: Any, v: Any) -> Any:
                split = [t.unflatten(2, (heads, -1)).transpose(1, 2) for t in (q, k, v)]
                return functional.scaled_dot_product_attention(*split).transpose(1, 2).flatten(2)

            @staticmethod
            def symbolic(g: Any, q: Any, k: Any, v: Any) -> Any:
                return g.op("com.microsoft::MultiHeadAttention", q, k, v, num_heads_i=heads)

        return MultiHeadAttention

    functions = {heads: function(heads) for heads in (1, 2, 4)}  # small0's head counts

    def attend(self: Any, q: Any, k: Any, v: Any) -> Any:  # (batch, heads, seq, head_dim)
        heads, dim = int(q.shape[1]), int(q.shape[3])
        flat = [t.transpose(1, 2).flatten(2) for t in (q, k, v)]
        return functions[heads].apply(*flat).unflatten(2, (heads, dim)).transpose(1, 2)

    return attend


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
    from beat_this.inference import Audio2Frames

    frames = Audio2Frames("small0")
    out: dict[str, Any] = {}
    for name, clips in INPUTS.items():
        audio = load(clips)
        spect = frames.signal2spect(audio, 22050)
        beat, downbeat = frames.spect2frames(spect)
        if name == "comp":  # one spectrogram is enough to check ours, and keeps the file small
            out["comp.spect"] = spect.numpy()
        out |= {
            f"{name}.beat": beat.numpy(),
            f"{name}.downbeat": downbeat.numpy(),
        }
        print(f"{name}: {len(audio) / 22050:.0f} s")
    np.savez_compressed(HERE / "reference.npz", **out)


if __name__ == "__main__":
    {"model": export_model, "reference": record_reference}[sys.argv[1]]()
