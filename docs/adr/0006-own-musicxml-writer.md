# ADR-0006: Write MusicXML ourselves instead of using music21

- Status: accepted
- Date: 2026-10-04
- Amends: "music21 for MusicXML" in CLAUDE.md

## Context

The notation stage turns `quantized.json` into MusicXML. CLAUDE.md named music21 (BSD-3).
Measured and tested on our needs (music21 10.5):

| | music21 |
|---|---|
| Install | 184 MB (pulls in matplotlib, requests, joblib) |
| Import | 2.8 s cold, 0.13 s warm; ~90-100 MB memory |
| Pickup bars | not exported as a pickup (`implicit`) bar without manual measure surgery |
| Determinism | random part/instrument ids on every run, so the same input gives different bytes, which breaks content-hash caching (ADR-0001) and golden-file tests |
| Spelling | its own default spelling of black keys, ignoring the key signature (F# in E-flat major) |

Our input is already constrained: every boundary is on a sixteenth or triplet-eighth grid
(`quantize`), 4/4, one pickup at most.

## Decision

`pipeline/musicxml.py` writes MusicXML 4.0 (partwise) with the standard library's
ElementTree: 12 divisions per quarter, one voice per staff (chords at shared onsets), splitting
at bar lines and beats with ties, triplet brackets per beat, rests, pickup bar 0
(`implicit="yes"`), key-aware spelling (flats in flat keys), a treble-8vb clef for guitar and a
grand staff split at middle C for piano. A regrid step makes edited scores that mix grids inside
a beat writable.

Tests: randomized scores (both instruments, all pickups and keys) must give bars whose
durations add up exactly per staff, with matched ties and tuplet brackets; golden files pin the
exact bytes (`UPDATE_GOLDEN=1` to update deliberately); an independent parser (music21, run
once outside the project) read the golden files and a real pipeline output correctly.

## Consequences

- No dependency, byte-identical output, notation stage runs in milliseconds.
- We own ~300 lines of notation code and its limits (TD-14): no beaming hints, one voice per
  staff, simple hand split.
- If notation needs grow a lot (multiple voices, other meters, engraving details), revisit
  music21 or another library behind the same `write_score` function.
