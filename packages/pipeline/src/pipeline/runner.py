"""Runs stages in order over a work dir, reusing cached results (ADR-0001)."""

import logging
import shutil
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from pipeline.config import PipelineConfig
from pipeline.errors import PipelineError, StageFailedError
from pipeline.hashing import sha256_file, sha256_json
from pipeline.stage import MANIFEST, SourceStage, Stage, StageContext, StageInputs
from pipeline.types import ArtifactRef, StageManifest, StageName, StageOutput
from pipeline.version import pipeline_version

logger = logging.getLogger(__name__)

_SCRATCH_PREFIXES = (".tmp-", ".old-")

StageStatus = Literal["ran", "cached", "skipped"]


@dataclass(frozen=True)
class StageResult:
    stage: StageName
    status: StageStatus
    duration_s: float


@dataclass(frozen=True)
class RunResult:
    pipeline_version: str
    stages: list[StageResult]
    outputs: dict[type[StageOutput], StageOutput]

    def output[O: StageOutput](self, kind: type[O]) -> O:
        value = self.outputs.get(kind)
        if not isinstance(value, kind):
            raise KeyError(kind.__name__)
        return value


def run_pipeline(
    source: Path,
    workdir: Path,
    cfg: PipelineConfig,
    stages: Sequence[Stage[Any]],
    *,
    force_from: StageName | None = None,
) -> RunResult:
    """Run `stages` after the built-in source stage.

    A stage is skipped as cached when its manifest's cache key matches and its artifacts are
    intact. `force_from` re-runs that stage and every stage after it regardless of the cache.
    """
    all_stages: list[Stage[Any]] = [SourceStage(source), *stages]
    names = [s.name for s in all_stages]
    if len(set(names)) != len(names):
        raise PipelineError(f"duplicate stage names: {names}")
    if force_from is not None and force_from not in names:
        raise PipelineError(f"--from-stage {force_from} is not in this pipeline")
    force_index = names.index(force_from) if force_from is not None else len(names)

    workdir.mkdir(parents=True, exist_ok=True)
    _remove_scratch_dirs(workdir)
    version = pipeline_version((s.name, s.version) for s in all_stages)

    outputs: dict[type[StageOutput], StageOutput] = {}
    results: list[StageResult] = []
    for index, stage in enumerate(all_stages):
        if not stage.applies(cfg):
            results.append(StageResult(stage.name, "skipped", 0.0))
            logger.info("stage skipped", extra={"stage": stage.name})
            continue

        inputs = _collect_inputs(stage, workdir, outputs)
        key = _cache_key(stage, cfg, inputs)
        start = time.perf_counter()
        cached = None if index >= force_index else _load_cached(stage, workdir, key)
        status: StageStatus
        if cached is not None:
            output, status = cached, "cached"
        else:
            output, status = _execute(stage, inputs, cfg, workdir, key, version), "ran"
        duration = time.perf_counter() - start

        outputs[stage.output_type] = output
        results.append(StageResult(stage.name, status, duration))
        logger.info(
            "stage done", extra={"stage": stage.name, "status": status, "duration_s": duration}
        )

    return RunResult(version, results, outputs)


def _collect_inputs(
    stage: Stage[Any], workdir: Path, outputs: dict[type[StageOutput], StageOutput]
) -> StageInputs:
    missing = [t.__name__ for t in stage.requires if t not in outputs]
    if missing:
        raise PipelineError(
            f"stage '{stage.name}' requires {', '.join(missing)}, which no earlier stage produced"
        )
    return StageInputs(workdir, {t: outputs[t] for t in stage.requires})


def _cache_key(stage: Stage[Any], cfg: PipelineConfig, inputs: StageInputs) -> str:
    return sha256_json(
        {
            "stage": str(stage.name),
            "version": stage.version,
            "config": cfg.model_dump(mode="json"),
            "fingerprint": dict(stage.fingerprint()),
            "inputs": {str(t.stage): o.model_dump(mode="json") for t, o in inputs.outputs.items()},
        }
    )


def _load_cached[O: StageOutput](stage: Stage[O], workdir: Path, key: str) -> O | None:
    try:
        manifest = StageManifest.model_validate_json((workdir / stage.name / MANIFEST).read_bytes())
    except (OSError, ValidationError):
        return None
    if manifest.cache_key != key:
        return None
    for ref in manifest.artifacts:
        path = workdir / ref.path
        if not path.is_file() or sha256_file(path) != ref.sha256:
            logger.warning("cached artifact missing or changed", extra={"path": ref.path})
            return None
    try:
        return stage.output_type.model_validate(manifest.output)
    except ValidationError:
        return None


def _execute[O: StageOutput](
    stage: Stage[O],
    inputs: StageInputs,
    cfg: PipelineConfig,
    workdir: Path,
    key: str,
    version: str,
) -> O:
    tmp = workdir / f".tmp-{stage.name}-{uuid.uuid4().hex}"
    tmp.mkdir()
    created_at = datetime.now(UTC)
    start = time.perf_counter()
    try:
        output = stage.run(inputs, StageContext(stage.name, tmp, cfg))
        if not isinstance(output, stage.output_type):
            raise TypeError(f"returned {type(output).__name__}, expected {stage.output_type}")
        artifacts = output.artifacts()
        _check_artifacts(stage.name, tmp, artifacts)
        manifest = StageManifest(
            stage=stage.name,
            stage_version=stage.version,
            pipeline_version=version,
            cache_key=key,
            output=output.model_dump(mode="json"),
            artifacts=artifacts,
            created_at=created_at,
            duration_s=time.perf_counter() - start,
        )
        (tmp / MANIFEST).write_text(manifest.model_dump_json(indent=2))
        _replace_dir(tmp, workdir / stage.name)
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        raise StageFailedError(stage.name, exc) from exc
    return output


def _check_artifacts(stage: StageName, out_dir: Path, artifacts: list[ArtifactRef]) -> None:
    prefix = f"{stage}/"
    for ref in artifacts:
        name = ref.path.removeprefix(prefix)
        if not ref.path.startswith(prefix) or "/" in name or not (out_dir / name).is_file():
            raise PipelineError(f"artifact {ref.path!r} was not written by stage '{stage}'")


def _replace_dir(new: Path, dest: Path) -> None:
    """Swap `new` into place. A crash between the renames leaves no `dest`, which just re-runs."""
    old = dest.with_name(f".old-{dest.name}-{uuid.uuid4().hex}")
    if dest.exists():
        dest.rename(old)
    new.rename(dest)
    shutil.rmtree(old, ignore_errors=True)


def _remove_scratch_dirs(workdir: Path) -> None:
    for child in workdir.iterdir():
        if child.is_dir() and child.name.startswith(_SCRATCH_PREFIXES):
            shutil.rmtree(child, ignore_errors=True)
