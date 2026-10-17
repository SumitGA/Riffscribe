# GAPS guitar note model (vendored, converted)

| | |
|---|---|
| File | `guitar.onnx` (33 MB) |
| Source | `guitar-gaps-paper-version-12200_iterations.pth` from [xavriley/midi-transcription-models](https://huggingface.co/xavriley/midi-transcription-models) at revision `b7bec65`; the model of Riley, Guo, Edwards, Dixon, "GAPS: A Large and Diverse Classical Guitar Dataset and Benchmark Transcription Model" (ISMIR 2024) |
| sha256 | `96c8da87246edef3c17d2a490f79df2396cb73927baf80de6b54e3f3f90c7742` |
| Licence | MIT, Copyright (c) 2025 Xavier Riley (declared on the model card; the card ships no licence file, so `LICENSE` is the standard MIT text). Fine-tuned from Kong et al.'s piano model, CC BY 4.0: attribution in `NOTICE` and the app's Acknowledgements. |

Converted, not copied: the 99 MB PyTorch checkpoint is exported to ONNX with int8 convolutions
and fully connected weights and float16 storage of the GRU weights by
`tests/fixtures/gaps/make_reference.py model`. The log-mel spectrogram and note decoding are
ported in `pipeline/gaps.py`; why this model, its cost and the training-data caveat are in
ADR-0014.
