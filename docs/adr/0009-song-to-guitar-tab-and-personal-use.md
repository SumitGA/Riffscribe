# ADR-0009: Goal is song to guitar tab; transcriptions are for personal use

- Status: accepted
- Date: 2026-10-08
- Changes: CLAUDE.md's v1 scope (solo guitar or piano; full-band mixes out of scope)

## Context

After using the app on a phone with a real guitar take, the product owner set the goal: people
upload a **song** and get **tabs for the guitar parts** in it: strummed chords, lead and riffs,
and fingerpicking. Two findings shaped how to get there:

- Transcription quality on solo guitar isn't good enough yet. On the owner's recording, Basic
  Pitch found one note at 49 of 67 strums (chords are lost at note detection, not in the tab
  stage); on GuitarSet, chord-comping clips reach note recall 0.58-0.76 against 0.88-1.0 for
  solos, and tab string accuracy is 2-44 % (TD-15, TD-16).
- A guitar separated from a mix (Demucs) is a solo guitar with artefacts, so song mode can only
  be as good as solo transcription. Separation can't tell two guitars apart yet, and costs minutes
  per song on CPU.

Users will upload commercial recordings. The compositions belong to publishers, and tabs are what
publishers license to Ultimate Guitar and Songsterr. Terms that make the uploader responsible are
needed but don't cover what the service itself does (store the audio, generate tabs).

## Decision

- Build toward song to guitar tab in steps, each measured (`make test-accuracy`, plus labelled
  recordings from the owner):
  - **A. Solo guitar quality:** chord recognition with chord names and tab in real chord shapes,
    a stronger licence-checked note model, a realistic playback sound with ringing notes, and the
    original recording in sync with the score.
  - **B. Song mode:** separate the guitar stem (GPU workers become necessary), chords for the
    whole song, tab for the parts that come through clearly.
  - **C.** Several guitars, distorted electric guitar, techniques.
- **Personal use only.** A transcription is private to the person who uploaded it: no public song
  pages, sharing links, catalogue or community tabs. Uploaded audio is deleted after processing,
  on a fixed retention period; separated stems stay internal. No marketing with artist or song
  names.
- Before a public launch: terms of service (the uploader confirms their right to use the audio
  and indemnifies the service; personal use only), an upload checkbox, a privacy policy, a
  takedown contact and process with a repeat-infringer policy, and DMCA agent registration if
  serving US users. A lawyer in the business's country reviews all of it.

## Consequences

- Step A comes before song mode and before more app features; staging stays useful for testing
  either way.
- Song mode brings GPU workers forward (ADR-0004's CPU-only MVP covers solo recordings only).
- Public sharing of song transcriptions is ruled out unless the business licenses compositions
  from publishers later.
- An audio-retention job (delete sources after N days) and the upload checkbox are needed before
  song mode reaches users.
