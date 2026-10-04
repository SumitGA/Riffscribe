import hashlib
import importlib.metadata
from collections.abc import Iterable

PACKAGE_VERSION = importlib.metadata.version("tabscribe-pipeline")


def pipeline_version(stage_versions: Iterable[tuple[str, str]]) -> str:
    """`{package}+{hash of every (stage, version)}`: bumping any stage changes it (ADR-0001)."""
    joined = ";".join(f"{name}={version}" for name, version in stage_versions)
    return f"{PACKAGE_VERSION}+{hashlib.sha256(joined.encode()).hexdigest()[:8]}"
