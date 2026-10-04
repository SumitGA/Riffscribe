# Basic Pitch model (vendored)

| | |
|---|---|
| File | `nmp.onnx` (ICASSP 2022 model) |
| Source | `basic-pitch==0.4.0` wheel, `basic_pitch/saved_models/icassp_2022/nmp.onnx` |
| sha256 | `2c3c1d144bfa61ad236e92e169c13535c880469a12a047d4e73451f2c059a0ec` |
| Licence | Apache-2.0, Copyright 2022 Spotify AB. See `LICENSE` and `NOTICE` in this folder |

The model file is unmodified. The pre- and post-processing code is ported, with changes, in
`pipeline/basic_pitch.py`. Why we vendor it instead of installing the package, and the
training-data caveat, are in `docs/tech-debt/README.md` (TD-11).
