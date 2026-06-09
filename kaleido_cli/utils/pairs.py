"""Trading pair helpers for canonical and reversed pair lookup."""

from __future__ import annotations

from collections.abc import Sequence

import typer
from kaleido_sdk import TradableAssetResponseModel, TradingPairResponseModel

from kaleido_cli.output import is_interactive, print_error, print_info


def canonical_pair(pair: TradingPairResponseModel) -> str:
    """Return the canonical BASE/QUOTE representation for a trading pair."""
    return f"{pair.base.ticker}/{pair.quote.ticker}".upper()


def reversed_pair(pair: TradingPairResponseModel) -> str:
    """Return the reversed QUOTE/BASE representation for a trading pair."""
    return f"{pair.quote.ticker}/{pair.base.ticker}".upper()


def pair_assets(
    pair: TradingPairResponseModel, is_reversed: bool
) -> tuple[TradableAssetResponseModel, TradableAssetResponseModel]:
    """Return the from/to assets for the user-requested pair direction."""
    if is_reversed:
        return pair.quote, pair.base
    return pair.base, pair.quote


def resolve_asset_id_for_layer(asset: TradableAssetResponseModel, layer: str) -> str:
    """Resolve the exact asset identifier to use for the selected layer."""
    normalized_layer = layer.strip().upper()
    if normalized_layer.startswith("BTC"):
        if asset.ticker.strip().upper() == "BTC":
            return asset.asset_id
        raise ValueError(
            f"BTC* layers are only valid for BTC assets (got asset {asset.ticker!r} and layer {layer!r})."
        )

    if normalized_layer.startswith("RGB"):
        if asset.ticker.strip().upper() == "BTC":
            raise ValueError(
                f"RGB* layers are only valid for RGB assets (got asset {asset.ticker!r} and layer {layer!r})."
            )
        return asset.asset_id

    raise ValueError(f"Unsupported layer {layer!r} for asset {asset.ticker!r}.")


def resolve_trading_pair(
    pairs: Sequence[TradingPairResponseModel] | None, pair: str
) -> tuple[TradingPairResponseModel, bool] | None:
    """Resolve a user-supplied pair against the maker pair list in either direction."""
    normalized = pair.strip().upper()
    for item in pairs or []:
        if canonical_pair(item) == normalized:
            return item, False

        if reversed_pair(item) == normalized:
            return item, True
    return None


def _pair_direction_options(
    pairs: Sequence[TradingPairResponseModel] | None,
) -> list[tuple[str, TradingPairResponseModel, bool]]:
    options: list[tuple[str, TradingPairResponseModel, bool]] = []
    seen: set[str] = set()
    for item in pairs or []:
        for label, is_reversed in (
            (canonical_pair(item), False),
            (reversed_pair(item), True),
        ):
            if label in seen:
                continue
            seen.add(label)
            options.append((label, item, is_reversed))
    return options


def resolve_pair_from_options(
    pairs: Sequence[TradingPairResponseModel] | None,
    pair: str | None,
) -> str:
    """Validate an explicit pair or interactively select from live pair directions."""
    if pair is not None:
        normalized = pair.strip().upper()
        if resolve_trading_pair(pairs, normalized):
            return normalized
        print_error(f"Pair {pair!r} not found.")
        raise typer.Exit(1)

    if not is_interactive():
        print_error("PAIR argument is required in non-interactive mode.")
        raise typer.Exit(1)

    options = _pair_direction_options(pairs)
    if not options:
        print_error("No trading pairs are currently available.")
        raise typer.Exit(1)

    print_info("Available trading pairs:")
    for index, (label, item, is_reversed) in enumerate(options, start=1):
        route_count = len(item.routes or [])
        direction = " (reverse)" if is_reversed else ""
        status = " (inactive)" if not item.is_active else ""
        print_info(
            f"{index}. {label}{direction} - {route_count} route"
            f"{'' if route_count == 1 else 's'}{status}"
        )

    while True:
        selected = typer.prompt("Select trading pair number", type=int)
        if 1 <= selected <= len(options):
            return options[selected - 1][0]
        print_error(f"Select a number from 1 to {len(options)}.")


def default_layer_for_asset(ticker: str) -> str:
    """Return the default quote layer for an asset ticker."""
    return "BTC_LN" if ticker.strip().upper() == "BTC" else "RGB_LN"


def resolve_quote_layers(
    pair: str, from_layer: str | None, to_layer: str | None
) -> tuple[str, str]:
    """Resolve default layers from the user-requested pair direction."""
    base_ticker, _, quote_ticker = pair.partition("/")
    resolved_from_layer = from_layer or default_layer_for_asset(base_ticker)
    resolved_to_layer = to_layer or default_layer_for_asset(quote_ticker)
    return resolved_from_layer, resolved_to_layer
