"""Swapstring parsing and validation helpers."""

from __future__ import annotations

from dataclasses import dataclass

from kaleido_sdk import PairQuoteResponse
from kaleido_sdk import Swap as MakerSwap


@dataclass(frozen=True)
class DecodedSwapString:
    """Decoded swapstring payload returned by maker and node APIs."""

    from_amount: int
    from_asset: str
    to_amount: int
    to_asset: str
    expiry: int
    payment_hash: str


def _normalize_asset_identifier(value: str) -> str:
    """Normalize native asset tickers while preserving case-sensitive asset IDs."""
    normalized = value.strip()
    if ":" in normalized:
        return normalized
    return normalized.upper()


def decode_swapstring(swapstring: str) -> DecodedSwapString:
    """Parse a swapstring into its component fields."""
    parts = swapstring.strip().split("/")
    if len(parts) != 6:
        raise ValueError("Swapstring must contain 6 slash-separated fields.")

    from_amount, from_asset, to_amount, to_asset, expiry, payment_hash = parts
    try:
        return DecodedSwapString(
            from_amount=int(from_amount),
            from_asset=from_asset,
            to_amount=int(to_amount),
            to_asset=to_asset,
            expiry=int(expiry),
            payment_hash=payment_hash,
        )
    except ValueError as exc:
        raise ValueError("Swapstring contains invalid numeric fields.") from exc


def validate_swapstring_against_quote(
    decoded: DecodedSwapString,
    quote: PairQuoteResponse,
    *,
    payment_hash: str | None = None,
) -> None:
    """Ensure a swapstring matches the accepted quote and payment hash."""
    if _normalize_asset_identifier(decoded.from_asset) != _normalize_asset_identifier(
        quote.from_asset.asset_id
    ):
        raise ValueError(
            f"Swapstring from_asset {decoded.from_asset!r} does not match quote asset {quote.from_asset.asset_id!r}."
        )
    if _normalize_asset_identifier(decoded.to_asset) != _normalize_asset_identifier(
        quote.to_asset.asset_id
    ):
        raise ValueError(
            f"Swapstring to_asset {decoded.to_asset!r} does not match quote asset {quote.to_asset.asset_id!r}."
        )
    if decoded.from_amount != quote.from_asset.amount:
        raise ValueError(
            f"Swapstring from_amount {decoded.from_amount} does not match quote amount {quote.from_asset.amount}."
        )
    if decoded.to_amount != quote.to_asset.amount:
        raise ValueError(
            f"Swapstring to_amount {decoded.to_amount} does not match quote amount {quote.to_asset.amount}."
        )
    if payment_hash is not None and decoded.payment_hash != payment_hash:
        raise ValueError(
            f"Swapstring payment_hash {decoded.payment_hash!r} does not match expected payment hash {payment_hash!r}."
        )


def validate_swapstring_against_swap(
    decoded: DecodedSwapString,
    swap: MakerSwap,
    *,
    payment_hash: str | None = None,
) -> None:
    """Ensure a swapstring matches the maker's recorded swap payload."""
    if swap.from_asset is not None and _normalize_asset_identifier(
        decoded.from_asset
    ) != _normalize_asset_identifier(swap.from_asset):
        raise ValueError(
            f"Swapstring from_asset {decoded.from_asset!r} does not match maker swap asset {swap.from_asset!r}."
        )
    if swap.to_asset is not None and _normalize_asset_identifier(
        decoded.to_asset
    ) != _normalize_asset_identifier(swap.to_asset):
        raise ValueError(
            f"Swapstring to_asset {decoded.to_asset!r} does not match maker swap asset {swap.to_asset!r}."
        )
    if decoded.from_amount != swap.qty_from:
        raise ValueError(
            f"Swapstring from_amount {decoded.from_amount} does not match maker swap amount {swap.qty_from}."
        )
    if decoded.to_amount != swap.qty_to:
        raise ValueError(
            f"Swapstring to_amount {decoded.to_amount} does not match maker swap amount {swap.qty_to}."
        )
    expected_payment_hash = payment_hash or swap.payment_hash
    if decoded.payment_hash != expected_payment_hash:
        raise ValueError(
            f"Swapstring payment_hash {decoded.payment_hash!r} does not match expected payment hash {expected_payment_hash!r}."
        )
