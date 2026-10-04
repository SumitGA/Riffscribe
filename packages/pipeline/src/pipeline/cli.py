import importlib.metadata
from pathlib import Path
from typing import Annotated

import typer

from pipeline import _tabcore
from pipeline.config import Instrument, PipelineConfig
from pipeline.errors import PipelineError
from pipeline.runner import run_pipeline
from pipeline.stages import default_stages
from pipeline.types import StageName

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """TabScribe transcription pipeline."""


@app.command()
def version() -> None:
    """Print the package and Rust core versions."""
    typer.echo(f"tabscribe-pipeline {importlib.metadata.version('tabscribe-pipeline')}")
    typer.echo(f"tabcore {_tabcore.__version__}")


@app.command()
def transcribe(
    audio: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    out: Annotated[Path, typer.Option("--out", help="Work dir for stage artifacts.")],
    instrument: Annotated[Instrument, typer.Option(help="Instrument in the recording.")],
    from_stage: Annotated[
        StageName | None, typer.Option(help="Re-run this stage and all later ones.")
    ] = None,
    force: Annotated[bool, typer.Option(help="Ignore the cache and re-run everything.")] = False,
) -> None:
    """Transcribe AUDIO, writing each stage's artifacts under --out."""
    cfg = PipelineConfig(instrument=instrument)
    force_from = StageName.SOURCE if force else from_stage
    try:
        result = run_pipeline(audio, out, cfg, default_stages(), force_from=force_from)
    except PipelineError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(1) from exc

    typer.echo(f"pipeline {result.pipeline_version} -> {out}")
    for r in result.stages:
        typer.echo(f"  {r.stage:<11} {r.status:<7} {r.duration_s:7.2f}s")
