import os
from collections.abc import Callable
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


@pytest.fixture
def golden() -> Callable[[str, bytes], None]:
    """Compare output with tests/golden/<name>; `UPDATE_GOLDEN=1 make test` rewrites the files.

    Golden files are reviewed in the PR diff: an unexpected change there is a behaviour change.
    """

    def check(name: str, actual: bytes) -> None:
        path = GOLDEN_DIR / name
        if os.environ.get("UPDATE_GOLDEN") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(actual)
        assert path.exists(), f"missing golden file {name}; run with UPDATE_GOLDEN=1"
        assert actual == path.read_bytes(), f"{name} changed; if intended, run UPDATE_GOLDEN=1"

    return check
