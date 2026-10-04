//! `pipeline._tabcore`: Rust kernels for the CPU-bound parts of the pipeline.
//!
//! Pure Rust logic lives in plain modules (testable with `cargo test`);
//! this file only holds the thin PyO3 binding layer.

mod notes;

use numpy::{PyReadonlyArray2, PyUntypedArrayMethods};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;

/// Decode Basic Pitch activations into `(start_frame, end_frame, pitch_bin, amplitude)` notes.
/// See `rust/notes.rs` and `pipeline.basic_pitch.decode_notes`.
#[pyfunction]
#[pyo3(signature = (
    frames, onsets, *, onset_threshold, frame_threshold, min_note_frames,
    min_pitch_bin, max_pitch_bin, infer_onsets, melodia_trick, energy_tolerance
))]
#[allow(clippy::too_many_arguments)]
fn decode_notes(
    frames: PyReadonlyArray2<'_, f32>,
    onsets: PyReadonlyArray2<'_, f32>,
    onset_threshold: f64,
    frame_threshold: f64,
    min_note_frames: usize,
    min_pitch_bin: usize,
    max_pitch_bin: usize,
    infer_onsets: bool,
    melodia_trick: bool,
    energy_tolerance: usize,
) -> PyResult<Vec<(usize, usize, usize, f64)>> {
    if frames.shape() != onsets.shape() {
        return Err(PyValueError::new_err(
            "frames and onsets must have the same shape",
        ));
    }
    let (n_frames, n_bins) = (frames.shape()[0], frames.shape()[1]);
    let params = notes::Params {
        onset_threshold,
        frame_threshold,
        min_note_frames,
        min_pitch_bin,
        max_pitch_bin,
        infer_onsets,
        melodia_trick,
        energy_tolerance,
    };
    let events = notes::decode(
        frames.as_slice()?,
        onsets.as_slice()?,
        n_frames,
        n_bins,
        &params,
    );
    Ok(events
        .into_iter()
        .map(|n| (n.start, n.end, n.pitch_bin, n.amplitude))
        .collect())
}

#[pymodule]
fn _tabcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(decode_notes, m)?)?;
    Ok(())
}
