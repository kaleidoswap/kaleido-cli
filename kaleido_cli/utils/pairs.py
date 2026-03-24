"""Trading pair helpers for canonical and reversed pair lookup."""

from __future__ import annotations

from collections.abc import Sequence

from kaleido_sdk import TradableAsset, TradingPair


def canonical_pair(pair: TradingPair) -> str:
    """Return the canonical BASE/QUOTE representation for a trading pair."""
    return f"{pair.base.ticker}/{pair.quote.ticker}".upper()


def reversed_pair(pair: TradingPair) -> str:
    """Return the reversed QUOTE/BASE representation for a trading pair."""
    return f"{pair.quote.ticker}/{pair.base.ticker}".upper()


def pair_assets(pair: TradingPair, is_reversed: bool) -> tuple[TradableAsset, TradableAsset]:
    """Return the from/to assets for the user-requested pair direction."""
    if is_reversed:
        return pair.quote, pair.base
    return pair.base, pair.quote


def resolve_trading_pair(
    pairs: Sequence[TradingPair] | None, pair: str
) -> tuple[TradingPair, bool] | None:
    """Resolve a user-supplied pair against the maker pair list in either direction."""
    normalized = pair.strip().upper()
    for item in pairs or []:
        if canonical_pair(item) == normalized:
            return item, False

        if reversed_pair(item) == normalized:
            return item, True
    return None


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
