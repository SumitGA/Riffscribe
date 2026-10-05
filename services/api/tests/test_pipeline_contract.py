"""The API and platform don't import the pipeline (it brings the ML libraries); these tests keep
their copies of its stage list and options in sync with it."""

import itertools

import pytest

from api.schemas import Instrument, JobOptions, Tuning
from pipeline.config import Instrument as PipelineInstrument
from pipeline.config import PipelineConfig
from pipeline.config import Tuning as PipelineTuning
from pipeline.stages import default_stages
from tabscribe_platform.jobqueue import STAGES

pytestmark = pytest.mark.unit


def test_stage_order_matches_the_pipeline() -> None:
    assert tuple(str(stage.name) for stage in default_stages()) == STAGES


def test_enums_match_the_pipeline() -> None:
    assert {i.value for i in Instrument} == {i.value for i in PipelineInstrument}
    assert {t.value for t in Tuning} == {t.value for t in PipelineTuning}


@pytest.mark.parametrize(("instrument", "tuning"), list(itertools.product(Instrument, Tuning)))
def test_job_options_are_a_valid_pipeline_config(instrument: Instrument, tuning: Tuning) -> None:
    options = JobOptions(instrument=instrument, tuning=tuning, capo=3)
    config = PipelineConfig.model_validate(options.model_dump(mode="json"))
    assert (config.instrument.value, config.tuning.value, config.capo) == (instrument, tuning, 3)
