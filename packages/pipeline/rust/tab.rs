//! Guitar tab fingering: pick a (string, fret) for every note so each chord is playable and the
//! fretting hand moves as little as possible.
//!
//! Each chord (notes sharing an onset) gets candidate fingerings: every way to put its notes on
//! distinct strings, or to drop a note that can't fit. A static cost scores how comfortable a
//! fingering is; a transition cost scores hand movement between chords. Viterbi finds the
//! cheapest path. Only the `BEAM` cheapest fingerings per chord are kept, so the search is
//! linear in the number of chords.

/// Fingerings kept per chord.
pub const BEAM: usize = 64;
/// Frets the hand covers without stretching (e.g. frets 1-5 = span 4).
pub const COMFORT_SPAN: i32 = 4;

#[derive(Debug, Clone)]
pub struct Weights {
    /// Per fret of average hand height: prefer low positions.
    pub fret_height: f64,
    /// Per fret between the lowest and highest fretted note.
    pub span: f64,
    /// Extra per fret beyond `COMFORT_SPAN`.
    pub stretch: f64,
    /// Bonus per open string.
    pub open_string: f64,
    /// Per fret the hand position shifts between chords.
    pub movement: f64,
    /// Per note left out because no fingering fits.
    pub drop: f64,
}

impl Default for Weights {
    fn default() -> Self {
        Weights {
            fret_height: 0.3,
            span: 1.0,
            stretch: 10.0,
            open_string: 0.5,
            movement: 1.0,
            drop: 50.0,
        }
    }
}

/// `open[i]` is the sounding pitch of string i with capo applied; index 0 is the lowest string.
#[derive(Debug, Clone)]
pub struct Fretboard {
    pub open: Vec<i32>,
    pub max_fret: i32,
}

/// One note's position: `(string index from the lowest string, fret)`, or `None` if dropped.
pub type Position = Option<(usize, i32)>;

#[derive(Debug, Clone)]
struct Fingering {
    positions: Vec<Position>,
    cost: f64,
    hand: Option<i32>, // lowest fretted fret; None if every note is open or dropped
}

/// For each chord (MIDI pitches), the position of each of its notes, in the same order.
pub fn assign(chords: &[Vec<i32>], board: &Fretboard, weights: &Weights) -> Vec<Vec<Position>> {
    if chords.is_empty() {
        return Vec::new();
    }
    let layers: Vec<Vec<Fingering>> = chords
        .iter()
        .map(|chord| fingerings(chord, board, weights))
        .collect();

    // Viterbi: best[i][s] = cheapest total cost ending in fingering s of chord i.
    let mut best: Vec<Vec<f64>> = vec![layers[0].iter().map(|f| f.cost).collect()];
    let mut back: Vec<Vec<usize>> = vec![vec![0; layers[0].len()]];
    for i in 1..layers.len() {
        let (prev, here) = (&layers[i - 1], &layers[i]);
        let mut costs = Vec::with_capacity(here.len());
        let mut links = Vec::with_capacity(here.len());
        for f in here {
            let (link, cost) = prev
                .iter()
                .enumerate()
                .map(|(j, p)| (j, best[i - 1][j] + movement(p, f, weights)))
                .min_by(|a, b| a.1.total_cmp(&b.1))
                .expect("every chord has at least one fingering");
            costs.push(cost + f.cost);
            links.push(link);
        }
        best.push(costs);
        back.push(links);
    }

    let last = best.len() - 1;
    let mut state = argmin(&best[last]);
    let mut path = vec![0; layers.len()];
    for i in (0..layers.len()).rev() {
        path[i] = state;
        state = back[i][state];
    }
    path.iter()
        .enumerate()
        .map(|(i, &s)| layers[i][s].positions.clone())
        .collect()
}

fn movement(from: &Fingering, to: &Fingering, weights: &Weights) -> f64 {
    match (from.hand, to.hand) {
        (Some(a), Some(b)) => weights.movement * f64::from((a - b).abs()),
        _ => 0.0, // open strings free the hand
    }
}

fn argmin(costs: &[f64]) -> usize {
    (0..costs.len())
        .min_by(|&a, &b| costs[a].total_cmp(&costs[b]))
        .expect("non-empty")
}

/// All fingerings of one chord, cheapest first, at most `BEAM`.
fn fingerings(chord: &[i32], board: &Fretboard, weights: &Weights) -> Vec<Fingering> {
    let candidates: Vec<Vec<(usize, i32)>> = chord
        .iter()
        .map(|&pitch| {
            (0..board.open.len())
                .filter_map(|s| {
                    let fret = pitch - board.open[s];
                    (0..=board.max_fret).contains(&fret).then_some((s, fret))
                })
                .collect()
        })
        .collect();

    let mut found = Vec::new();
    let mut current = Vec::with_capacity(chord.len());
    enumerate(&candidates, 0, 0, &mut current, &mut found);
    let mut scored: Vec<Fingering> = found
        .into_iter()
        .map(|positions| score(positions, weights))
        .collect();
    // Stable sort keeps enumeration order on equal costs, so results are deterministic.
    scored.sort_by(|a, b| a.cost.total_cmp(&b.cost));
    scored.truncate(BEAM);
    scored
}

fn enumerate(
    candidates: &[Vec<(usize, i32)>],
    note: usize,
    used_strings: u32,
    current: &mut Vec<Position>,
    out: &mut Vec<Vec<Position>>,
) {
    if note == candidates.len() {
        out.push(current.clone());
        return;
    }
    for &(string, fret) in &candidates[note] {
        if used_strings & (1 << string) == 0 {
            current.push(Some((string, fret)));
            enumerate(
                candidates,
                note + 1,
                used_strings | (1 << string),
                current,
                out,
            );
            current.pop();
        }
    }
    current.push(None); // leave this note out
    enumerate(candidates, note + 1, used_strings, current, out);
    current.pop();
}

fn score(positions: Vec<Position>, weights: &Weights) -> Fingering {
    let fretted: Vec<i32> = positions
        .iter()
        .flatten()
        .map(|&(_, f)| f)
        .filter(|&f| f > 0)
        .collect();
    let open = positions.iter().flatten().filter(|&&(_, f)| f == 0).count();
    let dropped = positions.iter().filter(|p| p.is_none()).count();
    let (low, high) = (fretted.iter().min().copied(), fretted.iter().max().copied());

    let mut cost = weights.drop * dropped as f64 - weights.open_string * open as f64;
    if let (Some(low), Some(high)) = (low, high) {
        let mean = f64::from(fretted.iter().sum::<i32>()) / fretted.len() as f64;
        let span = high - low;
        cost += weights.fret_height * mean + weights.span * f64::from(span);
        cost += weights.stretch * f64::from((span - COMFORT_SPAN).max(0));
    }
    Fingering {
        positions,
        cost,
        hand: low,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const STANDARD: [i32; 6] = [40, 45, 50, 55, 59, 64];

    fn board(capo: i32) -> Fretboard {
        Fretboard {
            open: STANDARD.iter().map(|p| p + capo).collect(),
            max_fret: 24 - capo,
        }
    }

    fn frets_by_string(positions: &[Position]) -> Vec<Option<i32>> {
        let mut out = vec![None; 6];
        for &(s, f) in positions.iter().flatten() {
            out[s] = Some(f);
        }
        out
    }

    fn single_notes(pitches: &[i32]) -> Vec<Vec<i32>> {
        pitches.iter().map(|&p| vec![p]).collect()
    }

    #[test]
    fn open_e_major_uses_the_open_shape() {
        let path = assign(
            &[vec![40, 47, 52, 56, 59, 64]],
            &board(0),
            &Weights::default(),
        );
        assert_eq!(
            frets_by_string(&path[0]),
            [0, 2, 2, 1, 0, 0].map(Some).to_vec()
        );
    }

    #[test]
    fn c_major_scale_stays_in_open_position() {
        let scale = single_notes(&[48, 50, 52, 53, 55, 57, 59, 60]);
        let path = assign(&scale, &board(0), &Weights::default());
        let frets: Vec<i32> = path.iter().map(|c| c[0].unwrap().1).collect();
        assert!(frets.iter().all(|&f| f <= 3), "{frets:?}");
    }

    #[test]
    fn high_melody_stays_in_one_hand_position() {
        let melody = single_notes(&[76, 77, 79, 81, 79, 77]);
        let path = assign(&melody, &board(0), &Weights::default());
        let frets: Vec<i32> = path.iter().map(|c| c[0].unwrap().1).collect();
        let spread = frets.iter().max().unwrap() - frets.iter().min().unwrap();
        assert!(spread <= COMFORT_SPAN + 1, "{frets:?}");
    }

    #[test]
    fn notes_below_the_lowest_string_are_dropped() {
        let path = assign(&[vec![38, 45]], &board(0), &Weights::default());
        assert_eq!(path[0], vec![None, Some((1, 0))]);
    }

    #[test]
    fn seven_note_chord_drops_exactly_one_note() {
        let path = assign(
            &[vec![40, 45, 50, 55, 59, 64, 69]],
            &board(0),
            &Weights::default(),
        );
        assert_eq!(path[0].iter().filter(|p| p.is_none()).count(), 1);
    }

    #[test]
    fn capo_frets_are_relative_to_the_capo() {
        let path = assign(&[vec![42]], &board(2), &Weights::default());
        assert_eq!(path[0][0], Some((0, 0)));
    }
}
