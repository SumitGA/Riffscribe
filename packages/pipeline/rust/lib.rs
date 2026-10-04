//! `pipeline._tabcore`: Rust kernels for the CPU-bound parts of the pipeline.
//!
//! Pure Rust logic lives in plain modules (testable with `cargo test`);
//! this file only holds the thin PyO3 binding layer.

use pyo3::prelude::*;

#[pymodule]
fn _tabcore(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
