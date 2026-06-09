"""Tests for shared interactive prompt and option validation helpers."""

from __future__ import annotations

import pytest
import typer

from kaleido_cli.utils import prompts


def test_resolve_required_int_returns_supplied_value():
    assert prompts.resolve_required_int(42, "Amount", "--amount") == 42


def test_resolve_required_int_missing_non_interactive_exits(capsys):
    with pytest.raises(typer.Exit):
        prompts.resolve_required_int(None, "Amount", "--amount")

    assert "--amount is required in non-interactive mode." in capsys.readouterr().err


def test_resolve_accept_reject_requires_exactly_one():
    with pytest.raises(typer.Exit):
        prompts.resolve_accept_reject(False, False, "Accept?")


def test_require_option_when_set_preserves_single_option_wording(capsys):
    with pytest.raises(typer.Exit):
        prompts.require_option_when_set(
            None,
            "--asset-id",
            **{"--asset-amount": 10},
        )

    assert "--asset-amount requires --asset-id." in capsys.readouterr().err


def test_resolve_optional_text_treats_blank_as_missing_non_interactive():
    assert prompts.resolve_optional_text("", "Access token") == ""
