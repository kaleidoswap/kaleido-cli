"""Shared trading-pair quote resolution and request helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import typer
from kaleido_sdk import (
    Layer,
    PairQuoteRequest,
    PairQuoteResponse,
    SwapLegInput,
    TradingPairsResponse,
)

from kaleido_cli.output import is_interactive, print_error, print_info
from kaleido_cli.utils.pairs import (
    pair_assets,
    resolve_asset_id_for_layer,
    resolve_pair_from_options,
    resolve_quote_layers,
    resolve_trading_pair,
)
from kaleido_cli.utils.prompts import display_amount_to_raw, resolve_amount_pair


@dataclass(frozen=True, slots=True)
class QuoteInputs:
    pairs: TradingPairsResponse
    pair: str
    from_amount: str | None
    to_amount: str | None
    from_layer: str
    to_layer: str


@dataclass(frozen=True, slots=True)
class ResolvedQuote:
    inputs: QuoteInputs
    quote: PairQuoteResponse


async def resolve_quote_inputs(
    client: Any,
    *,
    pair: str | None,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str | None,
    to_layer: str | None,
    prompt_prefix: str,
) -> QuoteInputs:
    """Fetch live pairs before resolving pair, amount, and layer inputs."""
    if is_interactive():
        print_info("Fetching available trading pairs...")
    pairs: TradingPairsResponse = await client.maker.list_pairs()
    resolved_pair = resolve_pair_from_options(pairs.pairs, pair)
    resolved_from_amount, resolved_to_amount = resolve_amount_pair(
        from_amount,
        to_amount,
        prompt_prefix=prompt_prefix,
        default_choice="R",
        pair=resolved_pair,
    )
    resolved_from_layer, resolved_to_layer = resolve_quote_layers(
        resolved_pair, from_layer, to_layer
    )
    return QuoteInputs(
        pairs=pairs,
        pair=resolved_pair,
        from_amount=resolved_from_amount,
        to_amount=resolved_to_amount,
        from_layer=resolved_from_layer,
        to_layer=resolved_to_layer,
    )


def build_pair_quote_request(inputs: QuoteInputs) -> PairQuoteRequest:
    """Build an SDK quote request from a validated live pair selection."""
    resolved_pair = resolve_trading_pair(inputs.pairs.pairs, inputs.pair)
    if not resolved_pair:
        print_error(f"Pair {inputs.pair!r} not found.")
        raise typer.Exit(1)

    matched_pair, is_reversed = resolved_pair
    from_asset, to_asset = pair_assets(matched_pair, is_reversed)
    try:
        from_asset_id = resolve_asset_id_for_layer(from_asset, inputs.from_layer)
        to_asset_id = resolve_asset_id_for_layer(to_asset, inputs.to_layer)
    except ValueError as exc:
        print_error(str(exc))
        raise typer.Exit(1)

    resolved_from_amount = (
        display_amount_to_raw(
            inputs.from_amount,
            precision=from_asset.precision,
            asset_label=from_asset.ticker,
            option_name="--from-amount",
        )
        if inputs.from_amount is not None
        else None
    )
    resolved_to_amount = (
        display_amount_to_raw(
            inputs.to_amount,
            precision=to_asset.precision,
            asset_label=to_asset.ticker,
            option_name="--to-amount",
        )
        if inputs.to_amount is not None
        else None
    )

    return PairQuoteRequest(
        from_asset=SwapLegInput(
            asset_id=from_asset_id,
            layer=Layer(inputs.from_layer),
            amount=resolved_from_amount,
        ),
        to_asset=SwapLegInput(
            asset_id=to_asset_id,
            layer=Layer(inputs.to_layer),
            amount=resolved_to_amount,
        ),
    )


async def fetch_pair_quote(client: Any, inputs: QuoteInputs) -> PairQuoteResponse:
    """Request a quote using the shared validated request builder."""
    return await client.maker.get_quote(build_pair_quote_request(inputs))


async def resolve_and_fetch_quote(
    client: Any,
    *,
    pair: str | None,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str | None,
    to_layer: str | None,
    prompt_prefix: str,
) -> ResolvedQuote:
    """Resolve live quote inputs and fetch their quote in one shared flow."""
    inputs = await resolve_quote_inputs(
        client,
        pair=pair,
        from_amount=from_amount,
        to_amount=to_amount,
        from_layer=from_layer,
        to_layer=to_layer,
        prompt_prefix=prompt_prefix,
    )
    return ResolvedQuote(inputs=inputs, quote=await fetch_pair_quote(client, inputs))
