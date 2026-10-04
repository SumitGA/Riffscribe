"""notation: quantized score -> MusicXML (standard notation; tab comes from the tab stage)."""

from pipeline.musicxml import write_score
from pipeline.score import Score
from pipeline.stage import Stage, StageContext, StageInputs
from pipeline.stages.quantize import QuantizedScore
from pipeline.types import ArtifactRef, StageName, StageOutput


class Notation(StageOutput):
    stage = StageName.NOTATION
    musicxml: ArtifactRef  # score.musicxml, MusicXML 4.0 partwise
    measures: int


class NotationStage(Stage[Notation]):
    name = StageName.NOTATION
    version = "1"
    requires = (QuantizedScore,)
    output_type = Notation

    def run(self, inputs: StageInputs, ctx: StageContext) -> Notation:
        quantized = inputs.get(QuantizedScore)
        score = Score.model_validate_json(inputs.path(quantized.score).read_text())
        xml = write_score(score, ctx.cfg.instrument)
        ctx.path("score.musicxml").write_bytes(xml)
        return Notation(musicxml=ctx.ref("score.musicxml"), measures=xml.count(b"<measure "))
