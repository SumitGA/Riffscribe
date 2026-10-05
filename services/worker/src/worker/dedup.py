"""Dedup cache keys (CLAUDE.md: reuse results keyed on normalized audio + pipeline version)."""

from collections.abc import Sequence
from typing import Any

from pipeline.config import PipelineConfig
from pipeline.hashing import sha256_json
from pipeline.stage import SourceStage, Stage
from pipeline.version import pipeline_version


def full_pipeline_version(stages: Sequence[Stage[Any]]) -> str:
    """The version a whole run of `stages` records: the same value `run_pipeline` computes
    for the last stage, available before the later stages have run."""
    pairs = [(SourceStage.name, SourceStage.version), *((s.name, s.version) for s in stages)]
    return pipeline_version(pairs)


def result_cache_key(user_id: str, audio_sha256: str, version: str, config: dict[str, Any]) -> str:
    """Two jobs with this key would produce the same score.

    - `audio_sha256` hashes the normalized samples, so re-encoded copies of one recording match.
    - The config (instrument, tuning, capo, ...) changes the result, so it is part of the key.
    - The user ID keeps reuse within one user's jobs (tenant isolation, TD-19).
    """
    canonical = PipelineConfig.model_validate(config).model_dump(mode="json")  # with defaults
    return sha256_json(
        {
            "user_id": user_id,
            "audio_sha256": audio_sha256,
            "pipeline_version": version,
            "config": canonical,
        }
    )
