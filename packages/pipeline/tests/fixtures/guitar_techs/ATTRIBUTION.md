# Guitar-TECHS excerpts

The `.flac` and `.truth.json` files in this folder are derived from **Guitar-TECHS**, licensed
under [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

> Hegel Pedroza, Wallace Abreu, Ryan M. Corey, Iran R. Roman. "Guitar-TECHS: An Electric Guitar
> Dataset Covering Techniques, Musical Excerpts, Chords and Scales Using a Diverse Array of
> Hardware." ICASSP 2025. arXiv:2501.03720. Data: https://zenodo.org/records/14963133

**Changes made:** each file is a 20-second excerpt of a miked-amp recording (`audio/micamp`),
starting 0.5 s before the first annotated note (rounded down to 0.1 s), mixed to mono, resampled
to 44.1 kHz and re-encoded as 16-bit FLAC. The ground truth is converted from the per-string MIDI
(hexaphonic pickup) into a simpler JSON, shifted by each recording's measured MIDI offset
(`midi_latency_s`), with times relative to the excerpt and fret numbers computed for standard tuning.
`make_fixtures.py` reproduces everything.
