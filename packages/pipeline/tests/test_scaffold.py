import pytest
from typer.testing import CliRunner

from pipeline import _tabcore
from pipeline.cli import app

pytestmark = pytest.mark.unit


def test_rust_extension_loads() -> None:
    assert _tabcore.__version__ == "0.1.0"


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0
    assert "tabcore 0.1.0" in result.output
