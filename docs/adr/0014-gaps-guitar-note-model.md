# ADR-0014: Guitar notes from the GAPS model

- Status: accepted
- Date: 2026-10-17
- Amends: TD-11 (Basic Pitch stays for piano, chord recognition and the fallback beat tracker),
  TD-16 and TD-34 (Basic Pitch's guitar decoding and its extra-note rules are removed)

## Context

After beats were fixed (ADR-0013), users still heard wrong notes in guitar transcriptions: notes
nobody played, fake chords, missed notes, right notes in the wrong octave. All of these come from
the note model. Basic Pitch is a small general-purpose model; tuned decoding (TD-16) and two
hand-set rules (TD-34) took it to note F1 0.778 on the held-out Guitar-TECHS clips, with one note
in five reported wrongly.

The Step A5 spike (2026-10-09) found no better model with commercially usable weights. That was
wrong for one candidate: Riley et al.'s guitar models (ICASSP 2024; GAPS, ISMIR 2024) were
released on Hugging Face in September 2025 (`xavriley/midi-transcription-models`, MIT). They are
Kong et al.'s high-resolution piano CRNN fine-tuned on guitar. Measured as published, with
upstream's decoding and no rules of ours (note F1, onsets within 50 ms):

| | Basic Pitch + our rules | GAPS (`paper-version`) |
|---|---|---|
| Guitar-TECHS (held out) | P 0.805, R 0.774, F1 0.778; 63 extra notes, 33 of them octave errors | P 0.981, R 0.808, F1 0.883; 11 extra, 1 octave |
| GuitarSet test clips | 0.836 | 0.919 |
| Solos degraded like a phone in a room | 0.799, 35 octave ghosts | 0.885, 3 |

The other released guitar checkpoints (`guitar-gaps`, `guitar-fl`) scored 0.861 on Guitar-TECHS.
MuScriptor (CC BY-NC) and YourMT3 (GPL-3.0) are excluded by licence; TART has no weights.

As published it costs about 6 s of CPU per 30 s of audio on the staging VM (2 vCPU EPYC), against
0.2 s for Basic Pitch: four CRNNs over a 229-band spectrogram at 100 frames/s, and every second
of audio processed twice (10 s segments overlapping by half).

## Decision

- **Guitar notes come from GAPS `guitar-gaps-paper-version-12200_iterations`, converted to ONNX
  and vendored** (`pipeline/models/gaps/guitar.onnx`, 33 MB): exported after the log-mel
  extractor, int8 convolutions (static, calibrated on the GuitarSet tuning clips) except each
  network's first, int8 fully connected weights, GRU weights stored as float16
  (`tests/fixtures/gaps/make_reference.py`). Note F1 is the same as the float model's on every
  suite. Quantizing the layers after the convolutions statically too was barely faster but put
  flat steps in the onset curves that the peak picker read as extra notes (precision 0.97 ->
  0.83).
- **`pipeline/gaps.py`** ports the log-mel spectrogram (numpy, matches torchlibrosa to 0.03 dB)
  and upstream's note decoding (vectorised; identical notes on the reference clip). The audio is
  split into 10 s chunks overlapping by 1 s instead of by half: same notes, half the work. 30 s
  chunks are no faster and need twice the memory (610 vs 300 MB).
- **One decoding change:** a note ends when its frame probability falls to 0.2, not upstream's
  0.1 (meant for a piano's sustain pedal). Found notes don't change; where they end gets closer
  (offset F1 on the tuning clips 0.749 -> 0.768).
- **Piano keeps Basic Pitch**, with its default decoding. Basic Pitch also still runs on guitar
  jobs: its activations feed chord recognition (TD-26, tuned on them, 0.90 major/minor) and the
  onset envelope for the fallback beat tracker. It costs 0.2 s per 30 s.
- **Removed:** Basic Pitch's tuned guitar decoding with its level normalisation and tuning script
  (TD-16), and the retrigger and sub-octave rules (TD-34): on GAPS's notes they changed nothing.
- **Strum grouping retuned** (`StrumParams`, `tests/tuning/tune_strums.py`, now on Beat This!
  beats as in the pipeline): GAPS times each string of a strum where it was played, so strums are
  wider than Basic Pitch made them. Gap 0.09 -> 0.12 s, ring 0.05 -> 0.1 s.

## Consequences

- Accuracy suite, Guitar-TECHS (held out): note F1 0.778 -> 0.883, precision 0.805 -> 0.971,
  recall 0.774 -> 0.816, tab strings 0.595 -> 0.718, chords kept whole 0.794 -> 0.925. GuitarSet:
  note F1 0.836 -> 0.918, with offsets 0.554 -> 0.737, tab strings 0.843 -> 0.880.
  Playback (notes the app sounds within 100 ms of the played note, GuitarSet): 64 % -> 77 %.
  Phone-degraded solos through the whole pipeline: note F1 0.799 -> 0.887.
- Small losses: separate notes kept apart 0.975 -> 0.953 (Guitar-TECHS) and 0.998 -> 0.990
  (GuitarSet), from the wider strum grouping; offsets on Guitar-TECHS 0.543 -> 0.500 (GAPS learned
  classical guitar, where notes ring on). See TD-36.
- Cost per job: ~1.8 s of CPU per 30 s of audio on the staging VM (2 threads), ~18 s for a
  5-minute song, peak ~300 MB, returned after each chunk. The worker image grows by 33 MB.
- The `paper-version` checkpoint is from the 2024 paper, before Guitar-TECHS (2025) existed, so
  Guitar-TECHS stays held out; whether it saw GuitarSet isn't documented, so its GuitarSet
  numbers may flatter it, as they flatter Basic Pitch (TD-11).
- GAPS trained on classical guitar recordings sourced from YouTube (GAPS) and, through Kong's
  model, on MAESTRO piano: the same training-data question as Basic Pitch (TD-11) for the legal
  review. Kong's weights are CC BY 4.0, so the model carries an attribution (`NOTICE`, the app's
  Acknowledgements).
