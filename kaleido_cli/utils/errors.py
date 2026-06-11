"""Shared CLI command error handling."""

from __future__ import annotations

from typing import NoReturn

import typer

from kaleido_cli.output import print_error


def raise_cli_error(error: Exception, *, prefix: str = "Error") -> NoReturn:
    """Preserve deliberate CLI exits and normalize unexpected command errors."""
    if isinstance(error, (typer.Exit, typer.Abort)):
        raise error
    print_error(f"{prefix}: {error}")
    raise typer.Exit(1)
