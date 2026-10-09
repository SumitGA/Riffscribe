# Tab position prior

`string_counts.json`: for each MIDI pitch, how many annotated notes were played on each string
(lowest string first, standard tuning). `pipeline/tab.py` turns it into a cost per string and
fret, so the fingering prefers the strings guitarists actually use for a pitch.

Counted by `tests/tuning/tune_tab.py --write-prior` from the note annotations of the 48
GuitarSet excerpts in the tuning set (never the committed test clips).

Derived from **GuitarSet** (version 1.1.0), licensed under
[Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

> Qingyang Xi, Rachel M. Bittner, Johan Pauwels, Xuzhou Ye, Juan P. Bello.
> "GuitarSet: A Dataset for Guitar Transcription." Proceedings of the 19th International Society
> for Music Information Retrieval Conference (ISMIR), 2018. https://zenodo.org/records/3371780

**Changes made:** only per-pitch note counts per string are kept; no audio or note sequences.
