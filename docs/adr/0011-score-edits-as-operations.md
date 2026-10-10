# ADR-0011: Score edits as operations, re-rendered by the worker

- Status: accepted
- Date: 2026-10-10
- Builds on: ADR-0001 (stage contract), ADR-0006 (our MusicXML writer), ADR-0010

## Context

Phase 4 lets users correct a transcription: move a note to another string or fret, change its
pitch, delete it, add a missed note or change how long a note lasts. CLAUDE.md requires edits to
be saved as new `score_versions`, never overwriting the original.

The app shows scores with alphaTab, which can change its in-memory model and redraw, and can
export Guitar Pro and alphaTex, but not MusicXML. Our canonical outputs are MusicXML (notation
and tab) and MIDI, written by the pipeline from its structured score (`quantized.json`) and tab
positions (`tab.json`).

## Decision

- **An edit is a list of operations** on the structured score of a base version:
  `set_position` (same pitch, another string/fret), `set_pitch`, `delete`, `add` and
  `set_duration`. Notes are addressed by `(onset_beats, pitch)`, which the quantizer already
  makes unique; beats are exact fractions sent as strings (`"3/2"`).
- **Each version keeps its editable document** (`score.json`: the `Score`, the tab positions,
  tuning, capo and the audio's trim offset) next to its rendered files. Version 0 gets one
  when a job finishes; older jobs get one built from their stage artifacts on first edit.
- **`POST /jobs/{id}/versions`** takes `{base_version, edits}` and returns the new version as
  `pending`. It is refused with 409 if `base_version` isn't the latest (another save won), so
  edits never apply to a stale score. The API validates only the request's shape; it never runs
  pipeline code (CLAUDE.md: the API stays light).
- **A `render` message on the CPU queue** makes the worker load the base document, apply the
  operations (`pipeline.edits.apply_edits`, which also checks them: frets must exist on the
  string, notes mustn't collide), and write the version's MusicXML, tab MusicXML, MIDI and
  `sync.json` with the same writers the pipeline uses. The version becomes `ready` or `failed`
  with a message the app shows.
- **Versions are immutable.** Restoring an old version creates a new one with its content.
- **The app** applies each operation to alphaTab's model at once for instant feedback, keeps
  local undo/redo, sends the list on Save and swaps in the server's version when it's ready.

## Consequences

- Every export (PDF, Guitar Pro, MusicXML, MIDI) works the same for edited versions, and the
  server can refuse impossible edits.
- Edit lists are small and readable: later they're the data to fit tab fingering to (TD-15).
- Saving takes a round trip through the queue (a second or two) before the new version's files
  exist; the app shows its local result meanwhile.
- The app and the pipeline both implement the operations (alphaTab model vs `Score`); tests on
  both sides use the same cases so they don't drift.
