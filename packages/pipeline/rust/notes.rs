//! Basic Pitch note decoding: a port of upstream `output_to_notes_polyphonic` (Apache-2.0,
//! Spotify AB, basic-pitch 0.4.0), modified as described below.
//!
//! The algorithm, thresholds and visiting order match upstream, so the same notes come out.
//! Changes, all for speed and memory:
//! - Out-of-range pitches and inferred onsets are computed on the fly instead of copying the
//!   activation matrices several times as float64.
//! - The "melodia trick" finds the loudest remaining cell with a max-heap. Upstream rescans the
//!   whole matrix (n_frames x 88) for every candidate note.
//! - If no frame activation ever rises, upstream divides by zero and gets NaN onsets (so no
//!   onset-based notes); here inferred onsets fall back to the predicted ones.

use std::cmp::Ordering;
use std::collections::BinaryHeap;

/// Decoding settings. Pitch bins are 0-based (bin 0 = MIDI 21) and inclusive.
#[derive(Debug, Clone)]
pub struct Params {
    pub onset_threshold: f64,
    pub frame_threshold: f64,
    pub min_note_frames: usize,
    pub min_pitch_bin: usize,
    pub max_pitch_bin: usize,
    pub infer_onsets: bool,
    pub melodia_trick: bool,
    pub energy_tolerance: usize,
}

/// A decoded note in frame units; `end` is exclusive.
#[derive(Debug, Clone, PartialEq)]
pub struct NoteEvent {
    pub start: usize,
    pub end: usize,
    pub pitch_bin: usize,
    pub amplitude: f64,
}

/// Activation matrices, row-major `(n_frames, n_bins)`, with out-of-range pitches read as 0.
struct Grid<'a> {
    frames: &'a [f32],
    onsets: &'a [f32],
    n_frames: usize,
    n_bins: usize,
    params: &'a Params,
}

impl Grid<'_> {
    fn in_range(&self, bin: usize) -> bool {
        (self.params.min_pitch_bin..=self.params.max_pitch_bin).contains(&bin)
    }

    fn frame(&self, t: usize, bin: usize) -> f64 {
        if self.in_range(bin) {
            f64::from(self.frames[t * self.n_bins + bin])
        } else {
            0.0
        }
    }

    fn onset(&self, t: usize, bin: usize) -> f64 {
        if self.in_range(bin) {
            f64::from(self.onsets[t * self.n_bins + bin])
        } else {
            0.0
        }
    }

    /// Upstream `get_infered_onsets` with n_diff = 2: the smaller of the rises over the last
    /// one and two frames, clamped at 0, and 0 for the first two frames.
    fn frame_rise(&self, t: usize, bin: usize) -> f64 {
        if t < 2 {
            return 0.0;
        }
        let now = self.frame(t, bin);
        (now - self.frame(t - 1, bin))
            .min(now - self.frame(t - 2, bin))
            .max(0.0)
    }

    fn max_over_grid(&self, value: impl Fn(usize, usize) -> f64) -> f64 {
        let mut max = f64::NEG_INFINITY;
        for t in 0..self.n_frames {
            for bin in 0..self.n_bins {
                max = max.max(value(t, bin));
            }
        }
        max
    }
}

pub fn decode(
    frames: &[f32],
    onsets: &[f32],
    n_frames: usize,
    n_bins: usize,
    params: &Params,
) -> Vec<NoteEvent> {
    assert_eq!(frames.len(), n_frames * n_bins, "frames shape");
    assert_eq!(onsets.len(), n_frames * n_bins, "onsets shape");
    if n_frames < 2 || n_bins == 0 {
        return Vec::new();
    }
    let grid = Grid {
        frames,
        onsets,
        n_frames,
        n_bins,
        params,
    };

    // Onset strength: predicted onsets, or their max with rescaled frame rises.
    let scale = if params.infer_onsets {
        let max_rise = grid.max_over_grid(|t, b| grid.frame_rise(t, b));
        let max_onset = grid.max_over_grid(|t, b| grid.onset(t, b));
        (max_rise > 0.0).then_some((max_onset, max_rise))
    } else {
        None
    };
    let strength = |t: usize, bin: usize| match scale {
        Some((max_onset, max_rise)) => grid
            .onset(t, bin)
            .max(max_onset * grid.frame_rise(t, bin) / max_rise),
        None => grid.onset(t, bin),
    };

    // Peaks in time (scipy argrelmax: strictly greater than both neighbours) above threshold.
    let mut peaks = Vec::new();
    for t in 1..n_frames - 1 {
        for bin in 0..n_bins {
            let s = strength(t, bin);
            if s > strength(t - 1, bin) && s > strength(t + 1, bin) && s >= params.onset_threshold {
                peaks.push((t, bin));
            }
        }
    }

    let mut remaining: Vec<f32> = (0..n_frames * n_bins)
        .map(|i| grid.frame(i / n_bins, i % n_bins) as f32)
        .collect();
    let mut notes = Vec::new();

    // Latest onsets first, as upstream does; the order decides which overlapping notes win.
    for &(start, bin) in peaks.iter().rev() {
        if start >= n_frames - 1 {
            continue;
        }
        let (mut i, mut k) = (start + 1, 0);
        while i < n_frames - 1 && k < params.energy_tolerance {
            k = if below(&remaining, i, bin, n_bins, params) {
                k + 1
            } else {
                0
            };
            i += 1;
        }
        i -= k;
        if i - start <= params.min_note_frames {
            continue;
        }
        clear(&mut remaining, start, i, bin, n_bins);
        notes.push(note(&grid, start, i, bin));
    }

    if params.melodia_trick {
        melodia(&grid, &mut remaining, &mut notes);
    }
    notes
}

/// Upstream "melodia trick": grow notes from the loudest leftover energy without an onset.
fn melodia(grid: &Grid<'_>, remaining: &mut [f32], notes: &mut Vec<NoteEvent>) {
    let (n_frames, n_bins, params) = (grid.n_frames, grid.n_bins, grid.params);
    // Cells only ever drop to 0, so a heap entry is current exactly while its cell is non-zero.
    let mut heap: BinaryHeap<Cell> = remaining
        .iter()
        .enumerate()
        .filter(|&(_, &v)| f64::from(v) > params.frame_threshold)
        .map(|(index, &value)| Cell { value, index })
        .collect();

    while let Some(Cell { index, .. }) = heap.pop() {
        if remaining[index] == 0.0 {
            continue;
        }
        let (mid, bin) = (index / n_bins, index % n_bins);
        remaining[index] = 0.0;

        let (mut i, mut k) = (mid + 1, 0);
        while i < n_frames - 1 && k < params.energy_tolerance {
            k = if below(remaining, i, bin, n_bins, params) {
                k + 1
            } else {
                0
            };
            clear(remaining, i, i + 1, bin, n_bins);
            i += 1;
        }
        let end = i as isize - 1 - k as isize;

        let (mut i, mut k) = (mid as isize - 1, 0);
        while i > 0 && k < params.energy_tolerance {
            k = if below(remaining, i as usize, bin, n_bins, params) {
                k + 1
            } else {
                0
            };
            clear(remaining, i as usize, i as usize + 1, bin, n_bins);
            i -= 1;
        }
        let start = i + 1 + k as isize;

        if end - start <= params.min_note_frames as isize {
            continue;
        }
        notes.push(note(grid, start as usize, end as usize, bin));
    }
}

fn below(remaining: &[f32], t: usize, bin: usize, n_bins: usize, params: &Params) -> bool {
    f64::from(remaining[t * n_bins + bin]) < params.frame_threshold
}

/// Zero a note's energy in its own pitch bin and both neighbours.
fn clear(remaining: &mut [f32], start: usize, end: usize, bin: usize, n_bins: usize) {
    let (low, high) = (bin.saturating_sub(1), (bin + 1).min(n_bins - 1));
    for t in start..end {
        remaining[t * n_bins + low..=t * n_bins + high].fill(0.0);
    }
}

fn note(grid: &Grid<'_>, start: usize, end: usize, bin: usize) -> NoteEvent {
    let sum: f64 = (start..end).map(|t| grid.frame(t, bin)).sum();
    NoteEvent {
        start,
        end,
        pitch_bin: bin,
        amplitude: sum / (end - start) as f64,
    }
}

/// Heap entry ordered like numpy's argmax: largest value first, then the lowest flat index.
#[derive(Debug, PartialEq)]
struct Cell {
    value: f32,
    index: usize,
}

impl Eq for Cell {}

impl Ord for Cell {
    fn cmp(&self, other: &Self) -> Ordering {
        self.value
            .total_cmp(&other.value)
            .then_with(|| other.index.cmp(&self.index))
    }
}

impl PartialOrd for Cell {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const BINS: usize = 4;

    fn params() -> Params {
        Params {
            onset_threshold: 0.5,
            frame_threshold: 0.3,
            min_note_frames: 3,
            min_pitch_bin: 0,
            max_pitch_bin: BINS - 1,
            infer_onsets: false,
            melodia_trick: true,
            energy_tolerance: 2,
        }
    }

    /// One sustained note in `bin` over frames [start, end), with an onset spike at `start`.
    fn grids(n_frames: usize, bin: usize, start: usize, end: usize) -> (Vec<f32>, Vec<f32>) {
        let mut frames = vec![0.0; n_frames * BINS];
        let mut onsets = vec![0.0; n_frames * BINS];
        for t in start..end {
            frames[t * BINS + bin] = 0.8;
        }
        onsets[start * BINS + bin] = 0.9;
        (frames, onsets)
    }

    #[test]
    fn finds_a_sustained_note_from_its_onset() {
        let (frames, onsets) = grids(20, 2, 5, 12);
        let notes = decode(&frames, &onsets, 20, BINS, &params());
        assert_eq!(notes.len(), 1);
        assert_eq!(
            (notes[0].start, notes[0].end, notes[0].pitch_bin),
            (5, 12, 2)
        );
        assert!((notes[0].amplitude - 0.8).abs() < 1e-6);
    }

    #[test]
    fn drops_notes_not_longer_than_the_minimum() {
        let (frames, onsets) = grids(20, 1, 5, 8);
        assert!(decode(&frames, &onsets, 20, BINS, &params()).is_empty());
    }

    #[test]
    fn melodia_finds_notes_without_onsets_only_when_enabled() {
        let (frames, _) = grids(20, 3, 4, 14);
        let silent = vec![0.0; 20 * BINS];
        let found = decode(&frames, &silent, 20, BINS, &params());
        assert_eq!(
            found.iter().map(|n| n.pitch_bin).collect::<Vec<_>>(),
            vec![3]
        );

        let off = Params {
            melodia_trick: false,
            ..params()
        };
        assert!(decode(&frames, &silent, 20, BINS, &off).is_empty());
    }

    #[test]
    fn ignores_pitches_outside_the_range() {
        let (frames, onsets) = grids(20, 0, 5, 12);
        let p = Params {
            min_pitch_bin: 1,
            ..params()
        };
        assert!(decode(&frames, &onsets, 20, BINS, &p).is_empty());
    }

    #[test]
    fn heap_pops_like_argmax() {
        let mut heap = BinaryHeap::from(vec![
            Cell {
                value: 0.5,
                index: 7,
            },
            Cell {
                value: 0.9,
                index: 9,
            },
            Cell {
                value: 0.9,
                index: 2,
            },
        ]);
        let order: Vec<usize> = std::iter::from_fn(|| heap.pop().map(|c| c.index)).collect();
        assert_eq!(order, vec![2, 9, 7]);
    }
}
