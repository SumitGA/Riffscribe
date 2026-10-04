"""tab: guitar fingering for the quantized score -> tab.json and tab.musicxml (notation + TAB)."""

from fractions import Fraction

from pipeline.config import Instrument, PipelineConfig
from pipeline.musicxml import TabLayout, write_score
from pipeline.score import Score
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.quantize import QuantizedScore
from pipeline.tab import TUNINGS, assign_tab
from pipeline.types import ArtifactRef, Frozen, StageName, StageOutput


class TabNote(Frozen):
    onset_beats: Fraction
    pitch: int
    string: int  # 1 = highest string
    fret: int  # relative to the capo


class TabFile(Frozen):
    """Contents of tab.json."""

    tuning: list[int]  # open-string pitches, lowest string first, without capo
    capo: int
    notes: list[TabNote]


class Tablature(StageOutput):
    stage = StageName.TAB
    tab: ArtifactRef  # tab.json (TabFile)
    musicxml: ArtifactRef  # tab.musicxml: notation staff + TAB staff
    unplayable_notes: int  # in the score but outside the instrument's reach


class TabStage(Stage[Tablature]):
    name = StageName.TAB
    version = "1"
    requires = (QuantizedScore,)
    output_type = Tablature

    def applies(self, cfg: PipelineConfig) -> bool:
        return cfg.instrument is Instrument.GUITAR

    def run(self, inputs: StageInputs, ctx: StageContext) -> Tablature:
        quantized = inputs.get(QuantizedScore)
        score = Score.model_validate_json(inputs.path(quantized.score).read_text())
        cfg = ctx.cfg
        positions = assign_tab(score.notes, cfg.tuning, cfg.capo)

        tab_file = TabFile(
            tuning=list(TUNINGS[cfg.tuning]),
            capo=cfg.capo,
            notes=[
                TabNote(onset_beats=onset, pitch=pitch, string=p.string, fret=p.fret)
                for (onset, pitch), p in sorted(positions.items())
            ],
        )
        ctx.path("tab.json").write_text(tab_file.model_dump_json(indent=1))
        layout = TabLayout(
            tuning=TUNINGS[cfg.tuning],
            capo=cfg.capo,
            positions={key: (p.string, p.fret) for key, p in positions.items()},
        )
        ctx.path("tab.musicxml").write_bytes(write_score(score, cfg.instrument, tab=layout))
        return Tablature(
            tab=ctx.ref("tab.json"),
            musicxml=ctx.ref("tab.musicxml"),
            unplayable_notes=len(score.notes) - len(positions),
        )
