"""Market data commands — assets, pairs, quotes."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_collection,
    output_model,
    print_error,
    print_json,
)
from kaleido_cli.utils.pairs import (
    canonical_pair,
    pair_assets,
    resolve_quote_layers,
    resolve_trading_pair,
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
        output_collection(
            "Tradeable Assets",
            [a.model_dump() for a in (resp.assets or [])],
            item_title="Asset — {index}",
        )
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
        items = []
        for p in resp.pairs or []:
            items.append(
                {
                    "pair": f"{p.base.ticker}/{p.quote.ticker}",
                    "base": p.base.model_dump() if hasattr(p.base, "model_dump") else p.base,
                    "quote": p.quote.model_dump() if hasattr(p.quote, "model_dump") else p.quote,
                    "routes": p.routes,
                    "routes_count": len(p.routes or []),
                    "is_active": p.is_active,
                }
            )
        output_collection("Trading Pairs", items, item_title="Pair — {index}")
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
        str | None,
        typer.Argument(
            help="Trading pair in [green]BASE/QUOTE[/green] format, e.g. [green]BTC/USDT[/green]."
        ),
    ] = None,
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
        str | None,
        typer.Option(
            "--from-layer",
            help="Source layer: [green]BTC_LN[/green], [green]RGB_LN[/green], [green]BTC_ONCHAIN[/green]. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: [green]BTC_LN[/green], [green]RGB_LN[/green], [green]BTC_ONCHAIN[/green]. Defaults from the requested pair direction.",
        ),
    ] = None,
) -> None:
    """Get a swap quote for a trading pair."""
    resolved_pair: str
    if pair is not None:
        resolved_pair = pair
    elif is_interactive():
        resolved_pair = typer.prompt("Trading pair (e.g. BTC/USDT)")
    else:
        print_error("PAIR argument is required in non-interactive mode.")
        raise typer.Exit(1)

    if from_amount is None and to_amount is None:
        if is_interactive():
            choice = typer.prompt("Quote by [S]end amount or [R]eceive amount?", default="S")
            if choice.strip().upper().startswith("R"):
                to_amount = typer.prompt("Amount to receive (raw units)", type=int)
            else:
                from_amount = typer.prompt("Amount to send (raw units)", type=int)
        else:
            print_error("Provide --from-amount or --to-amount in non-interactive mode.")
            raise typer.Exit(1)
    elif from_amount is not None and to_amount is not None:
        print_error("Provide exactly one of --from-amount or --to-amount.")
        raise typer.Exit(1)

    resolved_from_layer, resolved_to_layer = resolve_quote_layers(
        resolved_pair, from_layer, to_layer
    )
    asyncio.run(
        _market_quote(
            resolved_pair,
            from_amount,
            to_amount,
            resolved_from_layer,
            resolved_to_layer,
        )
    )


async def _market_quote(
    pair: str,
    from_amount: int | None,
    to_amount: int | None,
    from_layer: str,
    to_layer: str,
) -> None:
    from kaleido_sdk import Layer, PairQuoteRequest, SwapLegInput

    try:
        client = get_client()
        pairs = await client.maker.list_pairs()
        resolved_pair = resolve_trading_pair(pairs.pairs, pair)
        if not resolved_pair:
            print_error(
                f"Pair {pair!r} not found. Use 'kaleido market pairs' to list available pairs."
            )
            raise typer.Exit(1)
        matched_pair, is_reversed = resolved_pair
        from_asset, to_asset = pair_assets(matched_pair, is_reversed)

        body = PairQuoteRequest(
            from_asset=SwapLegInput(
                asset_id=from_asset.ticker,
                layer=Layer(from_layer),
                amount=from_amount,
            ),
            to_asset=SwapLegInput(
                asset_id=to_asset.ticker,
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


@market_app.command(
    "routes",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  List routes for BTC/USDT:\n"
        "  [cyan]kaleido market routes BTC/USDT[/cyan]\n\n"
        "  Raw JSON:\n"
        "  [cyan]kaleido --json market routes BTC/USDT[/cyan]"
    ),
)
def market_routes(
    pair: Annotated[
        str | None,
        typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT."),
    ] = None,
) -> None:
    """List available swap routes for a trading pair."""
    resolved_pair: str
    if pair is not None:
        resolved_pair = pair
    elif is_interactive():
        resolved_pair = typer.prompt("Trading pair (e.g. BTC/USDT)")
    else:
        print_error("PAIR argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_market_routes(resolved_pair))


async def _market_routes(pair: str) -> None:
    try:
        client = get_client()
        resolved_pair = resolve_trading_pair((await client.maker.list_pairs()).pairs, pair)
        if not resolved_pair:
            print_error(
                f"Pair {pair!r} not found. Use 'kaleido market pairs' to list available pairs."
            )
            raise typer.Exit(1)
        matched_pair, _ = resolved_pair
        routes = await client.maker.get_pair_routes(canonical_pair(matched_pair))
        if is_json_mode():
            print_json([r.model_dump() for r in routes])
            return
        output_collection(
            f"Routes — {pair.upper()}",
            [r.model_dump() for r in routes],
            item_title=f"Route — {pair.upper()} #{{index}}",
        )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@market_app.command(
    "analytics",
    epilog="  [cyan]kaleido market analytics[/cyan]   Get order statistics.",
)
def market_analytics() -> None:
    """Show Kaleidoswap order analytics and statistics."""
    asyncio.run(_market_analytics())


async def _market_analytics() -> None:
    try:
        client = get_client()
        stats = await client.maker.get_order_analytics()
        if is_json_mode():
            print_json(stats.model_dump())
        else:
            output_model(stats, title="Order Analytics")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
