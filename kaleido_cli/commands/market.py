"""Market data commands — assets, pairs, quotes."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_table,
)

market_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Query Kaleidoswap market data — assets, trading pairs, quotes, and maker info.",
)


@market_app.command(
    "assets",
    epilog=(
        "  [cyan]kaleido market assets[/cyan]          Table view\n"
        "  [cyan]kaleido --json market assets[/cyan]   Raw JSON"
    ),
)
def market_assets() -> None:
    """List all tradeable assets on Kaleidoswap."""
    asyncio.run(_market_assets())


async def _market_assets() -> None:
    try:
        client = get_client()
        resp = await client.maker.list_assets()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [[a.ticker, a.name, a.protocol_ids, a.precision] for a in (resp.assets or [])]
        print_table("Tradeable Assets", ["Ticker", "Name", "Protocol IDs", "Precision"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@market_app.command("pairs")
def market_pairs() -> None:
    """List all available trading pairs."""
    asyncio.run(_market_pairs())


async def _market_pairs() -> None:
    try:
        client = get_client()
        resp = await client.maker.list_pairs()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                f"{p.base.ticker}/{p.quote.ticker}",
                p.base.ticker,
                p.quote.ticker,
                len(p.routes or []),
                "yes" if p.is_active else "no",
            ]
            for p in (resp.pairs or [])
        ]
        print_table("Trading Pairs", ["Pair", "Base", "Quote", "Routes", "Active"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@market_app.command(
    "quote",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Quote: send 100 000 msat via Lightning, receive USDT via RGB Lightning:\n"
        "  [cyan]kaleido market quote BTC/USDT --from-amount 100000[/cyan]\n\n"
        "  Quote with explicit layers:\n"
        "  [cyan]kaleido market quote BTC/USDT --from-amount 100000 --from-layer BTC_LN --to-layer RGB_LN[/cyan]\n\n"
        "  Quote how much BTC is needed to receive 500 USDT:\n"
        "  [cyan]kaleido market quote BTC/USDT --to-amount 500 --from-layer BTC_LN --to-layer RGB_LN[/cyan]\n\n"
        "[bold]Available layers[/bold]: [green]BTC_LN[/green]  [green]RGB_LN[/green]  [green]BTC_ONCHAIN[/green]\n"
        "[dim]Use 'kaleido market pairs' to see available pair tickers.[/dim]"
    ),
)
def market_quote(
    pair: Annotated[
        str,
        typer.Argument(
            help="Trading pair in [green]BASE/QUOTE[/green] format, e.g. [green]BTC/USDT[/green]."
        ),
    ],
    from_amount: Annotated[
        int | None,
        typer.Option(
            "--from-amount",
            help="Amount to send (raw units of the base asset). Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        int | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive (raw units of the quote asset). Provide this OR --from-amount.",
        ),
    ] = None,
    from_layer: Annotated[
        str,
        typer.Option(
            "--from-layer",
            help="Source layer: [green]BTC_LN[/green], [green]RGB_LN[/green], [green]BTC_ONCHAIN[/green].",
        ),
    ] = "BTC_LN",
    to_layer: Annotated[
        str,
        typer.Option(
            "--to-layer",
            help="Destination layer: [green]BTC_LN[/green], [green]RGB_LN[/green], [green]BTC_ONCHAIN[/green].",
        ),
    ] = "RGB_LN",
) -> None:
    """Get a swap quote for a trading pair."""
    if from_amount is None and to_amount is None:
        print_error("Provide --from-amount or --to-amount.")
        raise typer.Exit(1)
    asyncio.run(_market_quote(pair, from_amount, to_amount, from_layer, to_layer))


async def _market_quote(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> None:
    from kaleidoswap_sdk import Layer, PairQuoteRequest, SwapLegInput

    try:
        client = get_client()
        pairs = await client.maker.list_pairs()
        matched = next(
            (p for p in (pairs.pairs or []) if f"{p.base.ticker}/{p.quote.ticker}" == pair.upper()),
            None,
        )
        if not matched:
            print_error(
                f"Pair {pair!r} not found. Use 'kaleido market pairs' to list available pairs."
            )
            raise typer.Exit(1)

        body = PairQuoteRequest(
            from_asset=SwapLegInput(
                asset_id=matched.base.ticker,
                layer=Layer(from_layer),
                amount=from_amount,
            ),
            to_asset=SwapLegInput(
                asset_id=matched.quote.ticker,
                layer=Layer(to_layer),
                amount=to_amount,
            ),
        )
        quote = await client.maker.get_quote(body)

        if is_json_mode():
            print_json(quote.model_dump())
            return

        output_model(quote, title=f"Quote — {pair.upper()}")
    except typer.Exit:
        raise
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@market_app.command("info")
def market_info() -> None:
    """Show Kaleidoswap maker node information."""
    asyncio.run(_market_info())


async def _market_info() -> None:
    try:
        client = get_client()
        info = await client.maker.get_swap_node_info()
        if is_json_mode():
            print_json(info.model_dump())
        else:
            output_model(info, title="Maker Node Info")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
