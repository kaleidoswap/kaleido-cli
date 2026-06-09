"""Market data commands — assets, pairs, quotes."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_json_mode,
    output_collection,
    output_model,
    print_error,
    print_json,
)
from kaleido_cli.utils.errors import raise_cli_error
from kaleido_cli.utils.pairs import (
    canonical_pair,
    resolve_trading_pair,
)
from kaleido_cli.utils.prompts import resolve_pair
from kaleido_cli.utils.quotes import resolve_and_fetch_quote

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
        raise_cli_error(e)


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
        raise_cli_error(e)


@market_app.command(
    "quote",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Quote: send BTC via Lightning, receive USDT via RGB Lightning:\n"
        "  [cyan]kaleido market quote BTC/USDT --from-amount 0.001[/cyan]\n\n"
        "  Quote with explicit layers:\n"
        "  [cyan]kaleido market quote BTC/USDT --from-amount 0.001 --from-layer BTC_LN --to-layer RGB_LN[/cyan]\n\n"
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
        str | None,
        typer.Option(
            "--from-amount",
            help="Amount to send in display units. Provide this OR --to-amount.",
        ),
    ] = None,
    to_amount: Annotated[
        str | None,
        typer.Option(
            "--to-amount",
            help="Amount to receive in display units. Provide this OR --from-amount.",
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
    asyncio.run(
        _market_quote(
            pair,
            from_amount,
            to_amount,
            from_layer,
            to_layer,
        )
    )


async def _market_quote(
    pair: str | None,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str | None,
    to_layer: str | None,
) -> None:
    try:
        client = get_client()
        resolved_quote = await resolve_and_fetch_quote(
            client,
            pair=pair,
            from_amount=from_amount,
            to_amount=to_amount,
            from_layer=from_layer,
            to_layer=to_layer,
            prompt_prefix="Quote",
        )
        quote = resolved_quote.quote

        if is_json_mode():
            print_json(quote.model_dump())
            return

        output_model(quote, title=f"Quote — {resolved_quote.inputs.pair}")
    except typer.Exit:
        raise
    except Exception as e:
        raise_cli_error(e)


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
        raise_cli_error(e)


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
    asyncio.run(_market_routes(resolve_pair(pair)))


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
        raise_cli_error(e)


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
        raise_cli_error(e)
