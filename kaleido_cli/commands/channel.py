"""Lightning channel commands — list, open, close."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer

from ..app import get_client
from ..output import is_json_mode, output_model, print_error, print_json, print_success, print_table

channel_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage Lightning channels — list, open a BTC or RGB colored channel, and close.",
)


@channel_app.command("list")
def channel_list() -> None:
    """List Lightning channels."""
    asyncio.run(_channel_list())


async def _channel_list() -> None:
    try:
        client = get_client(require_node=True)
        resp = await client.rln.list_channels()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                c.channel_id[:16] + "…" if c.channel_id else "-",
                c.peer_pubkey[:16] + "…" if c.peer_pubkey else "-",
                c.capacity_sat,
                c.outbound_balance_msat,
                c.inbound_balance_msat,
                "yes" if c.is_usable else "no",
                "yes" if c.ready else "no",
            ]
            for c in (resp.channels or [])
        ]
        print_table(
            "Channels",
            ["Channel ID", "Peer", "Capacity (sat)", "Outbound (msat)", "Inbound (msat)", "Usable", "Ready"],
            rows,
        )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "open",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Plain BTC channel (100 000 sat):\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000[/cyan]\n\n"
        "  Push 10 000 msat to the remote side on open:\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 --push-msat 10000[/cyan]\n\n"
        "  RGB colored channel (attach USDT):\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 \\\'\n"
        "      --asset-id rgb:abc... --asset-amount 5000[/cyan]\n\n"
        "  Private channel:\n"
        "  [cyan]kaleido channel open 03abc...@peer.host:9735 --capacity 100000 --private[/cyan]\n\n"
        "[dim]Peer format: pubkey@host:port[/dim]"
    ),
)
def channel_open(
    peer: Annotated[str, typer.Argument(help="Peer in [green]pubkey@host:port[/green] format.")],
    capacity: Annotated[int, typer.Option("--capacity", "-c", help="Channel capacity in satoshis.")],
    push_msat: Annotated[
        Optional[int], typer.Option("--push-msat", help="Millisatoshis to push to the remote side on open.")
    ] = None,
    asset_id: Annotated[Optional[str], typer.Option("--asset-id", help="RGB asset ID to attach (creates a colored channel).")] = None,
    asset_amount: Annotated[
        Optional[int], typer.Option("--asset-amount", help="Amount of RGB asset to place in the channel.")
    ] = None,
    public: Annotated[bool, typer.Option("--public/--private", help="Announce the channel publicly (default) or keep it private.")] = True,
) -> None:
    """Open a Lightning channel to a peer."""
    # Parse pubkey@host:port
    if "@" in peer:
        pubkey, addr = peer.split("@", 1)
    else:
        pubkey = peer
        addr = typer.prompt("Peer address (host:port)")

    asyncio.run(_channel_open(pubkey, addr, capacity, push_msat, asset_id, asset_amount, public))


async def _channel_open(
    pubkey: str,
    addr: str,
    capacity: int,
    push_msat: int | None,
    asset_id: str | None,
    asset_amount: int | None,
    public: bool,
) -> None:
    from kaleidoswap_sdk.rln import OpenChannelRequest

    try:
        client = get_client(require_node=True)
        body = OpenChannelRequest(
            peer_pubkey_and_opt_addr=f"{pubkey}@{addr}",
            capacity_sat=capacity,
            push_msat=push_msat,
            asset_id=asset_id,
            asset_amount=asset_amount,
            public=public,
        )
        resp = await client.rln.open_channel(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Channel opening initiated. Temporary channel ID: {resp.temporary_channel_id}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@channel_app.command(
    "close",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Cooperative close:\n"
        "  [cyan]kaleido channel close <channel-id> --peer 03abc...[/cyan]\n\n"
        "  Force close (unilateral, use only if peer is unresponsive):\n"
        "  [cyan]kaleido channel close <channel-id> --peer 03abc... --force[/cyan]\n\n"
        "[dim]Use 'kaleido channel list' to find channel IDs.[/dim]"
    ),
)
def channel_close(
    channel_id: Annotated[str, typer.Argument(help="Channel ID to close (from 'kaleido channel list').")],
    peer_pubkey: Annotated[str, typer.Option("--peer", help="Pubkey of the channel peer.")],
    force: Annotated[bool, typer.Option("--force", help="Force (unilateral) close. Use only if peer is offline.")] = False,
) -> None:
    """Close a Lightning channel."""
    asyncio.run(_channel_close(channel_id, peer_pubkey, force))


async def _channel_close(channel_id: str, peer_pubkey: str, force: bool) -> None:
    from kaleidoswap_sdk.rln import CloseChannelRequest

    try:
        client = get_client(require_node=True)
        await client.rln.close_channel(
            CloseChannelRequest(
                channel_id=channel_id,
                peer_pubkey=peer_pubkey,
                force=force,
            )
        )
        print_success("Channel close initiated.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
