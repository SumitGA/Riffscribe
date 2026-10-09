"""notation: quantized score -> MusicXML (standard notation; tab comes from the tab stage).

Also writes sync.json, which lines the bars up with the uploaded recording so a player can play
the recording in step with the score.
"""

import json

from pipeline.musicxml import bar_lines, write_score
from pipeline.rhythm import BeatMap
from pipeline.score import Score
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.normalize import NormalizedAudio
from pipeline.stages.quantize import QuantizedScore
from pipeline.types import ArtifactRef, StageName, StageOutput


class Notation(StageOutput):
    stage = StageName.NOTATION
    musicxml: ArtifactRef  # score.musicxml, MusicXML 4.0 partwise
    # sync.json: {"bar_starts_ms": [...]}, the time in the uploaded audio at which each bar of
    # the MusicXML (and tab.musicxml, which has the same bars) starts, first bar first
    sync: ArtifactRef
    measures: int


class NotationStage(Stage[Notation]):
    name = StageName.NOTATION
    version = "2"  # 2: sync.json
    requires = (NormalizedAudio, QuantizedScore)
    output_type = Notation

    def run(self, inputs: StageInputs, ctx: StageContext) -> Notation:
        quantized = inputs.get(QuantizedScore)
        score = Score.model_validate_json(inputs.path(quantized.score).read_text())
        xml = write_score(score, ctx.cfg.instrument)
        ctx.path("score.musicxml").write_bytes(xml)
        trim_s = inputs.get(NormalizedAudio).trim_start_s
        sync = {"bar_starts_ms": bar_starts_ms(score, trim_s)}
        ctx.path("sync.json").write_text(json.dumps(sync) + "\n")
        return Notation(
            musicxml=ctx.ref("score.musicxml"),
            sync=ctx.ref("sync.json"),
            measures=xml.count(b"<measure "),
        )


def bar_starts_ms(score: Score, trim_start_s: float) -> list[int]:
    """When each written bar starts in the uploaded audio (pipeline times + the trimmed lead-in).

    Beats outside the tracked ones are extrapolated at the nearest tempo; with fewer than two
    beats, bars follow the score tempo from the first beat.
    """
    bars = bar_lines(score)[:-1]
    if len(score.beat_times_s) >= 2:
        beat_map = BeatMap(score.beat_times_s)
        times = [beat_map.time_at(float(b)) for b in bars]
    else:
        start = score.beat_times_s[0] if score.beat_times_s else 0.0
        times = [start + float(b) * 60.0 / score.tempo_bpm for b in bars]
    return [round((t + trim_start_s) * 1000) for t in times]
