"""LSP (Lightning Service Provider) commands — info, network, channel orders, fees."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ChannelFees,
    ChannelOrderResponse,
    CreateOrderRequest,
    LspInfoResponse,
    NetworkInfoResponse,
    OrderRequest,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_success,
)

lsp_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Interact with the Kaleidoswap LSP (Lightning Service Provider) for channel management.",
)


@lsp_app.command(
    "info",
    epilog="  [cyan]kaleido lsp info[/cyan]   Show LSP capabilities and options.",
)
def lsp_info() -> None:
    """Show LSP information and available channel options."""
    asyncio.run(_lsp_info())


async def _lsp_info() -> None:
    try:
        client = get_client()
        resp: LspInfoResponse = await client.maker.get_lsp_info()
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="LSP Info")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "network-info",
    epilog="  [cyan]kaleido lsp network-info[/cyan]   Show LSP network/node information.",
)
def lsp_network_info() -> None:
    """Show LSP Lightning network information."""
    asyncio.run(_lsp_network_info())


async def _lsp_network_info() -> None:
    try:
        client = get_client()
        resp: NetworkInfoResponse = await client.maker.get_lsp_network_info()
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="LSP Network Info")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "estimate-fees",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Estimate fees for a 100 000 sat inbound channel:\n"
        "  [cyan]kaleido lsp estimate-fees --capacity-sat 100000[/cyan]\n\n"
        "[dim]Use 'kaleido lsp info' to see supported channel sizes.[/dim]"
    ),
)
def lsp_estimate_fees(
    capacity_sat: Annotated[
        int | None,
        typer.Option("--capacity-sat", help="Desired channel capacity in satoshis."),
    ] = None,
    push_sat: Annotated[
        int | None,
        typer.Option("--push-sat", help="Amount of satoshis to push to the other side on open."),
    ] = None,
    public: Annotated[
        bool,
        typer.Option("--public/--private", help="Whether the channel should be public."),
    ] = True,
    announces_channel: Annotated[
        bool,
        typer.Option("--announce/--no-announce", help="Announce the channel to the network."),
    ] = True,
) -> None:
    """Estimate fees for an LSP channel order."""
    if capacity_sat is None:
        if is_interactive():
            capacity_sat = typer.prompt("Channel capacity (satoshis)", type=int)
        else:
            print_error("--capacity-sat is required in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(_lsp_estimate_fees(capacity_sat, push_sat, public, announces_channel))


async def _lsp_estimate_fees(
    capacity_sat: int,
    push_sat: int | None,
    public: bool,
    announces_channel: bool,
) -> None:
    try:
        client = get_client()
        body = CreateOrderRequest(
            capacity_sat=capacity_sat,
            push_sat=push_sat,
            client_balance_sat=push_sat,
            public=public,
            announces_channel=announces_channel,
        )
        resp: ChannelFees = await client.maker.estimate_lsp_fees(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title="Estimated LSP Fees")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "order-create",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Create an order for a 100 000 sat channel:\n"
        "  [cyan]kaleido lsp order-create --capacity-sat 100000[/cyan]"
    ),
)
def lsp_order_create(
    capacity_sat: Annotated[
        int | None,
        typer.Option("--capacity-sat", help="Desired channel capacity in satoshis."),
    ] = None,
    push_sat: Annotated[
        int | None,
        typer.Option("--push-sat", help="Amount of satoshis to push to the local side."),
    ] = None,
    public: Annotated[
        bool,
        typer.Option("--public/--private", help="Whether the channel should be public."),
    ] = True,
    announces_channel: Annotated[
        bool,
        typer.Option("--announce/--no-announce", help="Announce the channel to the network."),
    ] = True,
) -> None:
    """Create an LSP channel order."""
    if capacity_sat is None:
        if is_interactive():
            capacity_sat = typer.prompt("Channel capacity (satoshis)", type=int)
        else:
            print_error("--capacity-sat is required in non-interactive mode.")
            raise typer.Exit(1)

    asyncio.run(_lsp_order_create(capacity_sat, push_sat, public, announces_channel))


async def _lsp_order_create(
    capacity_sat: int,
    push_sat: int | None,
    public: bool,
    announces_channel: bool,
) -> None:
    try:
        client = get_client()
        body = CreateOrderRequest(
            capacity_sat=capacity_sat,
            push_sat=push_sat,
            client_balance_sat=push_sat,
            public=public,
            announces_channel=announces_channel,
        )
        resp: ChannelOrderResponse = await client.maker.create_lsp_order(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"LSP order created: {resp.order.id if resp.order else '?'}")
            output_model(resp, title="LSP Order")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@lsp_app.command(
    "order-get",
    epilog="  [cyan]kaleido lsp order-get <order-id>[/cyan]",
)
def lsp_order_get(
    order_id: Annotated[
        str | None,
        typer.Argument(help="LSP order ID to retrieve."),
    ] = None,
) -> None:
    """Get details of an existing LSP channel order."""
    resolved_id: str
    if order_id is not None:
        resolved_id = order_id
    elif is_interactive():
        resolved_id = typer.prompt("Order ID")
    else:
        print_error("ORDER_ID argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_lsp_order_get(resolved_id))


async def _lsp_order_get(order_id: str) -> None:
    try:
        client = get_client()
        resp: ChannelOrderResponse = await client.maker.get_lsp_order(
            OrderRequest(order_id=order_id)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"LSP Order — {order_id[:16]}…")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
