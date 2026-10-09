//! `pipeline._tabcore`: Rust kernels for the CPU-bound parts of the pipeline.
//!
//! Pure Rust logic lives in plain modules (testable with `cargo test`);
//! this file only holds the thin PyO3 binding layer.

mod notes;
mod tab;

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

/// Tab fingering for chords of MIDI pitches: per chord, per note, `(string_index, fret)` with
/// string 0 = lowest, or `None` when the note can't be placed. See `rust/tab.rs`. Cost weights
/// left as `None` keep their defaults (`tab::Weights::default`); the tuning script sets them.
/// `position_cost[string][fret]` (string 0 = lowest) adds a cost per note placed there.
#[pyfunction]
#[pyo3(signature = (
    chords, open_strings, max_fret, *,
    fret_height=None, span=None, stretch=None, open_string=None, movement=None, shift=None,
    drop=None, position_cost=None
))]
#[allow(clippy::too_many_arguments)]
fn tab_positions(
    chords: Vec<Vec<i32>>,
    open_strings: Vec<i32>,
    max_fret: i32,
    fret_height: Option<f64>,
    span: Option<f64>,
    stretch: Option<f64>,
    open_string: Option<f64>,
    movement: Option<f64>,
    shift: Option<f64>,
    drop: Option<f64>,
    position_cost: Option<Vec<Vec<f64>>>,
) -> PyResult<Vec<Vec<tab::Position>>> {
    if open_strings.is_empty() || open_strings.len() > 32 {
        return Err(PyValueError::new_err(
            "open_strings must have 1 to 32 strings",
        ));
    }
    let board = tab::Fretboard {
        open: open_strings,
        max_fret,
        position_cost: position_cost.unwrap_or_default(),
    };
    let default = tab::Weights::default();
    let weights = tab::Weights {
        fret_height: fret_height.unwrap_or(default.fret_height),
        span: span.unwrap_or(default.span),
        stretch: stretch.unwrap_or(default.stretch),
        open_string: open_string.unwrap_or(default.open_string),
        movement: movement.unwrap_or(default.movement),
        shift: shift.unwrap_or(default.shift),
        drop: drop.unwrap_or(default.drop),
    };
    Ok(tab::assign(&chords, &board, &weights))
}

#[pymodule]
fn _tabcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add_function(wrap_pyfunction!(decode_notes, m)?)?;
    m.add_function(wrap_pyfunction!(tab_positions, m)?)?;
    Ok(())
}
