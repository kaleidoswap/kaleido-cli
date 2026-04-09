"""Shared interactive prompt helpers for CLI commands."""

from __future__ import annotations

import typer
from kaleido_sdk import parse_raw_amount

from kaleido_cli.output import is_interactive, print_error


def resolve_optional_text(value: str | None, prompt: str, default: str = "") -> str:
    if value is not None:
        return value
    if is_interactive():
        return typer.prompt(prompt, default=default)
    return default


def resolve_required_text(value: str | None, prompt: str, option_name: str) -> str:
    if value is not None:
        return value
    if is_interactive():
        return typer.prompt(prompt)
    print_error(f"{option_name} is required in non-interactive mode.")
    raise typer.Exit(1)


def resolve_pair(pair: str | None) -> str:
    if pair is not None:
        return pair
    if is_interactive():
        return typer.prompt("Trading pair (e.g. BTC/USDT)")
    print_error("PAIR argument is required in non-interactive mode.")
    raise typer.Exit(1)


def resolve_amount_pair(
    from_amount: str | None,
    to_amount: str | None,
    *,
    prompt_prefix: str,
    default_choice: str,
    pair: str,
) -> tuple[str | None, str | None]:
    base_ticker, _, quote_ticker = pair.partition("/")
    send_label = base_ticker or "base asset"
    receive_label = quote_ticker or "quote asset"
    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt(
                f"{prompt_prefix} by [S]end amount or [R]eceive amount?",
                default=default_choice,
            )
            if choice.strip().upper().startswith("R"):
                return None, typer.prompt(f"Amount to receive ({receive_label}, display units)")
            return typer.prompt(f"Amount to send ({send_label}, display units)"), None
        print_error("Provide --from-amount or --to-amount in non-interactive mode.")
        raise typer.Exit(1)
    if from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)
    return from_amount, to_amount


def display_amount_to_raw(
    value: str,
    *,
    precision: int | None,
    asset_label: str,
    option_name: str,
) -> int:
    normalized = value.strip()
    if not normalized:
        print_error(f"{option_name} cannot be empty.")
        raise typer.Exit(1)
    try:
        return parse_raw_amount(normalized, precision or 0)
    except ValueError as exc:
        print_error(f"{option_name} for {asset_label}: {exc}")
        raise typer.Exit(1)
