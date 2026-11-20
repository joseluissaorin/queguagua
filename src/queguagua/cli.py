"""`queguagua` (also `qg`): one command group per bus company. Output is JSON."""

import sys
from typing import Annotated

import typer

from . import package_version
from .alsa import cli as alsa_cli
from .output import render

COMPANIES = [
    {"id": "alsa", "name": "ALSA", "web": "https://www.alsa.es",
     "covers": "long distance, regional and airport buses in Spain, Portugal, France and Morocco",
     "features": ["search", "fares", "seats", "extras", "discounts", "abono-unico", "bonos", "login",
                  "checkout", "tickets", "cancel", "pdf", "tracking"]},
]

app = typer.Typer(
    name="queguagua",
    help="¿Qué guagua cojo? Spanish buses from the terminal: timetables, fares, seats, passes and checkout "
         "with your own account. One command group per company; every command prints JSON.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
app.add_typer(alsa_cli.app, name="alsa",
              help="ALSA (alsa.es): search, quote and buy, Abono Único, bonos, your Alsa Plus account and tickets.")


def _version(value: bool) -> None:
    if value:
        typer.echo(package_version)
        raise typer.Exit()


@app.callback()
def main_callback(
    version: Annotated[bool, typer.Option("--version", callback=_version, is_eager=True,
                                          help="Print the version and exit.")] = False,
) -> None:
    pass


@app.command()
def empresas() -> None:
    """The bus companies queguagua knows, and what it can do with each."""
    typer.echo(render({"count": len(COMPANIES), "companies": COMPANIES}))


def main() -> None:
    try:
        app()
    except KeyboardInterrupt:  # pragma: no cover
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
