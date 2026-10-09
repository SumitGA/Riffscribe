# GuitarSet excerpts

The `.flac` and `.truth.json` files in this folder are derived from **GuitarSet** (version 1.1.0),
licensed under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

> Qingyang Xi, Rachel M. Bittner, Johan Pauwels, Xuzhou Ye, Juan P. Bello.
> "GuitarSet: A Dataset for Guitar Transcription." Proceedings of the 19th International Society
> for Music Information Retrieval Conference (ISMIR), 2018. https://zenodo.org/records/3371780

**Changes made:** each file is a 20-second excerpt of the `audio_mono-mic` recording, starting
0.5 s before the first annotated note (rounded down to 0.1 s), re-encoded as 16-bit FLAC. The
ground truth is converted from the track's JAMS annotations (`note_midi` per string, `beat_position`,
`tempo`, and the performed `chord` annotation, cut to the excerpt) into a simpler JSON, with times shifted to the excerpt and pitches rounded to the nearest
semitone. `make_fixtures.py` reproduces everything.
