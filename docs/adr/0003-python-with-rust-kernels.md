# ADR-0003: Python orchestration with Rust kernels (PyO3)

- Status: accepted
- Date: 2026-10-04

## Context

We want compute and memory efficiency. Most pipeline time is spent inside native code that
Python only calls: PyTorch/Demucs, ONNX Runtime (Basic Pitch), ffmpeg, soxr, numpy/numba
(librosa). Rewriting those call sites in Rust saves almost nothing. Our *own* algorithms are
different: the tab-fingering Viterbi search is roughly 10^8 operations for a 5-minute piece,
which is seconds-to-minutes in pure Python and milliseconds in Rust.

## Decision

- Python stays the orchestration language (stages, I/O, ML calls, evaluation with mir_eval).
- CPU-bound kernels we write ourselves are implemented in **Rust**, in `packages/pipeline/rust/`,
  built with **maturin** into the same wheel as the extension module `pipeline._tabcore`.
- Pure Rust logic lives in plain modules tested with `cargo test`; `lib.rs` is only the thin PyO3
  binding layer. `_tabcore.pyi` keeps `mypy --strict` type-checking the boundary.
- The tab Viterbi and fretboard model are Rust from day one.

**Rule for moving more code to Rust:** a stage moves when profiling shows its time is spent in our
own Python code, not in an ML runtime or C library, and the gain matters for cost or latency.

## Consequences

- Two toolchains (uv + cargo) in dev and CI; contributors need Rust installed to build.
- Wheels are built per platform (abi3 means one wheel per OS/arch covers all CPython ≥ 3.12).
- The API (Phase 2) stays FastAPI; it is I/O-bound, and the decision can be revisited if load
  tests miss the p95 < 200 ms target.
- See `docs/tech-debt/README.md` (TD-5).
