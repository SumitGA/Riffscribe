import importlib.metadata

import typer

from pipeline import _tabcore

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """TabScribe transcription pipeline."""


@app.command()
def version() -> None:
    """Print the package and Rust core versions."""
    typer.echo(f"tabscribe-pipeline {importlib.metadata.version('tabscribe-pipeline')}")
    typer.echo(f"tabcore {_tabcore.__version__}")
