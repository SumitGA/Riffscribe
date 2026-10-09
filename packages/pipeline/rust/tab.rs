//! Guitar tab fingering: pick a (string, fret) for every note so each chord is playable and the
//! fretting hand moves as little as possible.
//!
//! Each chord (notes sharing an onset) gets candidate fingerings: every way to put its notes on
//! distinct strings, or to drop a note that can't fit. A static cost scores how comfortable a
//! fingering is. The hand is modelled explicitly: a *hand position* is the fret under the index
//! finger, and the hand reaches that fret and the next `COMFORT_SPAN` without moving. Viterbi runs over (fingering, hand position) pairs, so a melody inside one
//! box costs nothing to move through and only shifting the hand is charged. Open strings fit
//! any hand position, which lets the hand stay put across them. Only the `BEAM` cheapest
//! fingerings per chord are kept, so the search is linear in the number of chords.

/// Fingerings kept per chord.
pub const BEAM: usize = 64;
/// Frets the hand covers without stretching (e.g. frets 1-5 = span 4).
pub const COMFORT_SPAN: i32 = 4;

#[derive(Debug, Clone)]
pub struct Weights {
    /// Per fret of hand position: prefer low positions.
    pub fret_height: f64,
    /// Per fret between the lowest and highest fretted note.
    pub span: f64,
    /// Extra per fret beyond `COMFORT_SPAN`.
    pub stretch: f64,
    /// Bonus per open string.
    pub open_string: f64,
    /// Per fret the hand position shifts between chords.
    pub movement: f64,
    /// Per shift of the hand position, however far.
    pub shift: f64,
    /// Per note left out because no fingering fits.
    pub drop: f64,
}

/// Defaults grid-searched with the Python position prior (`pipeline/tab.py`) on the pipeline's
/// own transcriptions of 48 GuitarSet tuning excerpts (tests/tuning/tune_tab.py): 0.76 of comp
/// and 0.71 of solo notes land on the player's string. Hand height is left to the prior, and
/// any open-string bonus lowered solo accuracy (players solo on fretted notes).
impl Default for Weights {
    fn default() -> Self {
        Weights {
            fret_height: 0.0,
            span: 1.0,
            stretch: 10.0,
            open_string: 0.0,
            movement: 1.0,
            shift: 4.0,
            drop: 50.0,
        }
    }
}

/// `open[i]` is the sounding pitch of string i with capo applied; index 0 is the lowest string.
/// `position_cost[i][fret]` is an extra cost for playing a note there (e.g. how rarely players
/// use that string for that pitch); empty means none.
#[derive(Debug, Clone)]
pub struct Fretboard {
    pub open: Vec<i32>,
    pub max_fret: i32,
    pub position_cost: Vec<Vec<f64>>,
}

impl Fretboard {
    fn cost_at(&self, string: usize, fret: i32) -> f64 {
        self.position_cost
            .get(string)
            .and_then(|frets| frets.get(fret as usize))
            .copied()
            .unwrap_or(0.0)
    }
}

/// One note's position: `(string index from the lowest string, fret)`, or `None` if dropped.
pub type Position = Option<(usize, i32)>;

#[derive(Debug, Clone)]
struct Fingering {
    positions: Vec<Position>,
    cost: f64,
    fretted: Option<(i32, i32)>, // lowest and highest fretted fret; None if all open or dropped
}

/// A Viterbi state: a fingering of the chord played with the index finger at `hand`.
#[derive(Debug, Clone, Copy)]
struct State {
    fingering: usize,
    hand: i32,
}

/// For each chord (MIDI pitches), the position of each of its notes, in the same order.
pub fn assign(chords: &[Vec<i32>], board: &Fretboard, weights: &Weights) -> Vec<Vec<Position>> {
    if chords.is_empty() {
        return Vec::new();
    }
    let hands = 1..=board.max_fret.max(1);
    let layers: Vec<Vec<Fingering>> = chords
        .iter()
        .map(|chord| fingerings(chord, board, weights))
        .collect();
    let states: Vec<Vec<State>> = layers
        .iter()
        .map(|layer| hand_states(layer, hands.clone()))
        .collect();
    let static_cost = |i: usize, s: &State| {
        layers[i][s.fingering].cost + weights.fret_height * f64::from(s.hand - 1)
    };

    // Viterbi: best[i][k] = cheapest total cost ending in state k of chord i. The transition
    // depends only on the two hand positions, so take the best previous state per hand position
    // first: O(states + hand positions^2) per chord instead of O(states^2).
    let n_hands = (board.max_fret.max(1) + 1) as usize;
    let mut best: Vec<Vec<f64>> = vec![states[0].iter().map(|s| static_cost(0, s)).collect()];
    let mut back: Vec<Vec<usize>> = vec![vec![0; states[0].len()]];
    for i in 1..layers.len() {
        let mut by_hand = vec![(f64::INFINITY, 0usize); n_hands];
        for (k, s) in states[i - 1].iter().enumerate() {
            let slot = &mut by_hand[s.hand as usize];
            if best[i - 1][k] < slot.0 {
                *slot = (best[i - 1][k], k);
            }
        }
        let arrive: Vec<(f64, usize)> = (0..n_hands)
            .map(|to| {
                by_hand
                    .iter()
                    .enumerate()
                    .filter(|(_, (cost, _))| cost.is_finite())
                    .map(|(from, &(cost, k))| (cost + hand_shift(from, to, weights), k))
                    .min_by(|a, b| a.0.total_cmp(&b.0))
                    .unwrap_or((f64::INFINITY, 0))
            })
            .collect();
        let (costs, links) = states[i]
            .iter()
            .map(|s| {
                let (cost, link) = arrive[s.hand as usize];
                (cost + static_cost(i, s), link)
            })
            .unzip();
        best.push(costs);
        back.push(links);
    }

    let last = best.len() - 1;
    let mut state = argmin(&best[last]);
    let mut path = vec![0; layers.len()];
    for i in (0..layers.len()).rev() {
        path[i] = states[i][state].fingering;
        state = back[i][state];
    }
    path.iter()
        .enumerate()
        .map(|(i, &f)| layers[i][f].positions.clone())
        .collect()
}

/// Every hand position each fingering can be played from. Fretted notes must lie within the
/// hand's reach (`hand..=hand + COMFORT_SPAN`); a stretched fingering is played from its lowest
/// fret; a fingering with no fretted notes fits any position.
fn hand_states(layer: &[Fingering], hands: std::ops::RangeInclusive<i32>) -> Vec<State> {
    let mut states = Vec::new();
    for (fingering, f) in layer.iter().enumerate() {
        let range = match f.fretted {
            None => hands.clone(),
            Some((low, high)) if high - low > COMFORT_SPAN => low..=low,
            Some((low, high)) => (high - COMFORT_SPAN).max(*hands.start())..=low,
        };
        states.extend(range.map(|hand| State { fingering, hand }));
    }
    states
}

fn hand_shift(from: usize, to: usize, weights: &Weights) -> f64 {
    if from == to {
        return 0.0;
    }
    weights.shift + weights.movement * (from as f64 - to as f64).abs()
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
        .map(|positions| score(positions, board, weights))
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

/// Static cost: dropped notes, open strings, the fretted span and each note's position cost.
/// Hand height is charged per hand position in `assign`.
fn score(positions: Vec<Position>, board: &Fretboard, weights: &Weights) -> Fingering {
    let fretted: Vec<i32> = positions
        .iter()
        .flatten()
        .map(|&(_, f)| f)
        .filter(|&f| f > 0)
        .collect();
    let open = positions.iter().flatten().filter(|&&(_, f)| f == 0).count();
    let dropped = positions.iter().filter(|p| p.is_none()).count();
    let range = fretted
        .iter()
        .min()
        .copied()
        .zip(fretted.iter().max().copied());

    let mut cost = weights.drop * dropped as f64 - weights.open_string * open as f64;
    cost += positions
        .iter()
        .flatten()
        .map(|&(string, fret)| board.cost_at(string, fret))
        .sum::<f64>();
    if let Some((low, high)) = range {
        let span = high - low;
        cost += weights.span * f64::from(span);
        cost += weights.stretch * f64::from((span - COMFORT_SPAN).max(0));
    }
    Fingering {
        positions,
        cost,
        fretted: range,
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
            position_cost: Vec::new(),
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
    fn c_major_scale_stays_in_one_hand_position() {
        // Which position is the prior's job (pipeline/tab.py); the search keeps the hand still.
        let scale = single_notes(&[48, 50, 52, 53, 55, 57, 59, 60]);
        let path = assign(&scale, &board(0), &Weights::default());
        let frets: Vec<i32> = path.iter().map(|c| c[0].unwrap().1).collect();
        let fretted: Vec<i32> = frets.iter().copied().filter(|&f| f > 0).collect();
        let spread = fretted.iter().max().unwrap() - fretted.iter().min().unwrap();
        assert!(spread <= COMFORT_SPAN, "{frets:?}");
    }

    #[test]
    fn melody_inside_one_box_does_not_shift_the_hand() {
        // An A minor pentatonic lick: playable from one hand position (5th or 8th).
        let lick = single_notes(&[69, 72, 74, 72, 69, 67, 64, 67, 69]);
        let path = assign(&lick, &board(0), &Weights::default());
        let frets: Vec<i32> = path.iter().map(|c| c[0].unwrap().1).collect();
        let spread = frets.iter().max().unwrap() - frets.iter().min().unwrap();
        assert!(
            frets.iter().all(|&f| f > 0) && spread <= COMFORT_SPAN,
            "{frets:?}"
        );
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
        assert_eq!(path[0][0], None);
        let (string, fret) = path[0][1].unwrap();
        assert_eq!(STANDARD[string] + fret, 45);
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
    fn position_cost_moves_a_note_to_another_string() {
        let mut costly = board(0);
        costly.position_cost = vec![vec![0.0; 25]; 6];
        let free = assign(&[vec![45]], &board(0), &Weights::default());
        let (string, _) = free[0][0].unwrap();
        costly.position_cost[string] = vec![100.0; 25];
        let moved = assign(&[vec![45]], &costly, &Weights::default());
        assert_ne!(moved[0][0].unwrap().0, string);
    }

    #[test]
    fn capo_frets_are_relative_to_the_capo() {
        let path = assign(&[vec![42]], &board(2), &Weights::default());
        assert_eq!(path[0][0], Some((0, 0)));
    }
}
