"""Tests for shared CLI command error handling."""

from __future__ import annotations

import pytest
import typer

from kaleido_cli.utils.errors import raise_cli_error


def test_raise_cli_error_preserves_deliberate_exit(capsys):
    with pytest.raises(typer.Exit) as exc_info:
        raise_cli_error(typer.Exit(0))

    assert exc_info.value.exit_code == 0
    assert capsys.readouterr().err == ""


def test_raise_cli_error_normalizes_unexpected_error(capsys):
    with pytest.raises(typer.Exit) as exc_info:
        raise_cli_error(ValueError("boom"))

    assert exc_info.value.exit_code == 1
    assert "Error: boom" in capsys.readouterr().err
