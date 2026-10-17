# Beat This! model (vendored, converted)

| | |
|---|---|
| File | `small0.onnx` (3.0 MB) |
| Source | `small0` checkpoint of [Beat This!](https://github.com/CPJKU/beat_this) (CPJKU, JKU Linz), code at commit `b95c8ab` |
| sha256 | `2e869cdbd1e0b163c57bcc5daf73b4b471ee187f561a685160325f8104c7f044` |
| Licence | MIT, Copyright (c) 2024 Institute of Computational Perception, JKU Linz. See `LICENSE`. Upstream: "The code and the published model weights are released under the MIT license." |

Unlike `basic_pitch/`, this file is converted, not copied: the 8.1 MB PyTorch checkpoint is
exported to ONNX with fused attention, int8 matrix weights and short tensor names by
`tests/fixtures/beat_this/make_reference.py model`. Pre-processing and chunking are ported in
`pipeline/beat_this.py`; why this model and the training-data caveat are in ADR-0013.
