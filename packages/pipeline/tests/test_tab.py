from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import pytest
from test_musicxml import golden_score, make_score, measures, random_score, staff_durations

from pipeline.config import Instrument, PipelineConfig, Tuning
from pipeline.musicxml import DIVISIONS, TabLayout, write_score
from pipeline.runner import run_pipeline
from pipeline.score import Score
from pipeline.stages import default_stages
from pipeline.stages.tab import TabFile, Tablature
from pipeline.tab import MAX_FRET, TUNINGS, TabPosition, assign_tab
from pipeline.types import StageName

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).parent / "fixtures" / "basic_pitch"


def layout(score: Score, tuning: Tuning = Tuning.STANDARD, capo: int = 0) -> TabLayout:
    positions = assign_tab(score.notes, tuning, capo)
    return TabLayout(
        tuning=TUNINGS[tuning],
        capo=capo,
        positions={key: (p.string, p.fret) for key, p in positions.items()},
    )


def test_open_e_major_chord() -> None:
    score = make_score([(p, 0, 4) for p in (40, 47, 52, 56, 59, 64)])
    frets = {p.string: p.fret for p in assign_tab(score.notes, Tuning.STANDARD, 0).values()}

    assert frets == {6: 0, 5: 2, 4: 2, 3: 1, 2: 0, 1: 0}


@pytest.mark.parametrize("seed", range(10))
@pytest.mark.parametrize(("tuning", "capo"), [(Tuning.STANDARD, 0), (Tuning.DROP_D, 3)])
def test_every_position_sounds_the_right_pitch(seed: int, tuning: Tuning, capo: int) -> None:
    score = random_score(seed)
    positions = assign_tab(score.notes, tuning, capo)
    strings = TUNINGS[tuning]

    used: dict[Fraction, set[int]] = {}
    for (onset, pitch), p in positions.items():
        assert strings[len(strings) - p.string] + capo + p.fret == pitch
        assert 0 <= p.fret <= MAX_FRET - capo
        assert p.string not in used.setdefault(onset, set()), "two notes on one string"
        used[onset].add(p.string)


def test_low_d_needs_drop_d() -> None:
    score = make_score([(38, 0, 1), (45, 1, 1)])

    assert (Fraction(0), 38) not in assign_tab(score.notes, Tuning.STANDARD, 0)
    assert assign_tab(score.notes, Tuning.DROP_D, 0)[(Fraction(0), 38)] == TabPosition(6, 0)


def test_capo_frets_are_relative_to_the_capo() -> None:
    score = make_score([(42, 0, 1)])  # F#2: open low string with capo 2
    assert assign_tab(score.notes, Tuning.STANDARD, 2)[(Fraction(0), 42)] == TabPosition(6, 0)


@pytest.mark.parametrize("seed", range(10))
def test_tab_musicxml_bars_add_up_on_both_staves(seed: int) -> None:
    score = random_score(seed)
    xml = write_score(score, Instrument.GUITAR, tab=layout(score))

    for i, measure in enumerate(measures(xml)):
        expected = (score.pickup_beats if i == 0 and score.pickup_beats else 4) * DIVISIONS
        assert staff_durations(measure) == {"1": expected, "2": expected}, f"bar {i}"


def test_tab_staff_has_tuning_capo_and_string_fret() -> None:
    score = make_score([(52, 0, 1)])
    xml = write_score(score, Instrument.GUITAR, tab=layout(score, capo=2)).decode()

    assert "<sign>TAB</sign>" in xml and "<staff-lines>6</staff-lines>" in xml
    assert "<capo>2</capo>" in xml
    assert "<string>4</string>" in xml and "<fret>0</fret>" in xml  # E3 = open D string + 2


def test_golden_tab_musicxml(golden: Callable[[str, bytes], None]) -> None:
    score = golden_score()
    golden("tab_guitar.musicxml", write_score(score, Instrument.GUITAR, tab=layout(score)))


def test_tab_stage_through_the_whole_pipeline(tmp_path: Path) -> None:
    cfg = PipelineConfig(instrument=Instrument.GUITAR)
    result = run_pipeline(FIXTURES / "guitar_like.wav", tmp_path, cfg, default_stages())
    tab = result.output(Tablature)
    tab_file = TabFile.model_validate_json((tmp_path / tab.tab.path).read_text())

    assert len(tab_file.notes) > 0
    assert tab_file.tuning == list(TUNINGS[Tuning.STANDARD])
    assert b"<sign>TAB</sign>" in (tmp_path / tab.musicxml.path).read_bytes()


def test_tab_stage_is_skipped_for_piano(tmp_path: Path) -> None:
    cfg = PipelineConfig(instrument=Instrument.PIANO)
    result = run_pipeline(FIXTURES / "piano_like.wav", tmp_path, cfg, default_stages())

    assert {r.stage: r.status for r in result.stages}[StageName.TAB] == "skipped"


def test_position_prior_keeps_a_scale_in_a_low_position() -> None:
    scale = make_score([(p, i, 1) for i, p in enumerate([48, 50, 52, 53, 55, 57, 59, 60])])
    positions = assign_tab(scale.notes, Tuning.STANDARD, 0)

    assert all(p.fret <= 5 for p in positions.values()), positions


def test_a_stray_high_note_does_not_drag_a_solo_up_the_neck() -> None:
    # A box-position lick around fret 8 on the G and B strings, with one stray C6 (fret 20).
    lick = [63, 60, 65, 62, 67, 65, 68, 67, 84, 70, 72, 70, 68, 67, 65, 63]
    positions = assign_tab(
        make_score([(p, i, 1) for i, p in enumerate(lick)]).notes, Tuning.STANDARD, 0
    )

    lows = [p.fret for (_, pitch), p in positions.items() if pitch != 84]
    assert max(lows) <= 13, sorted(positions.items())
