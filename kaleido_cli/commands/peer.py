"""Peer connection commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer

from ..app import get_client
from ..output import is_json_mode, print_error, print_json, print_success, print_table
from kaleidoswap_sdk.rln import (
    ConnectPeerRequest,
    DisconnectPeerRequest,
    ListPeersResponse,
)

peer_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Manage peer connections — list, connect, disconnect.",
)


@peer_app.command("list")
def peer_list() -> None:
    """List connected peers."""
    asyncio.run(_peer_list())


async def _peer_list() -> None:
    try:
        client = get_client(require_node=True)
        resp: ListPeersResponse = await client.rln.list_peers()
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [[p.pubkey] for p in (resp.peers or [])]
        print_table("Peers", ["Pubkey"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@peer_app.command(
    "connect",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Connect to a peer using pubkey@host:port format:\n"
        "  [cyan]kaleido peer connect 03abc...def@peer.kaleidoswap.com:9735[/cyan]\n\n"
        "[dim]A peer connection is required before opening a channel.[/dim]"
    ),
)
def peer_connect(
    peer: Annotated[
        str,
        typer.Argument(help="Peer address in [green]pubkey@host:port[/green] format."),
    ],
) -> None:
    """Connect to a peer."""
    asyncio.run(_peer_connect(peer))


async def _peer_connect(peer: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.connect_peer(ConnectPeerRequest(peer_pubkey_and_addr=peer))
        print_success(f"Connected to {peer}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@peer_app.command(
    "disconnect",
    epilog="  [cyan]kaleido peer disconnect 03abc...def[/cyan]   Use 'kaleido peer list' to find pubkeys.",
)
def peer_disconnect(
    pubkey: Annotated[
        str, typer.Argument(help="Full pubkey of the peer to disconnect.")
    ],
) -> None:
    """Disconnect from a peer."""
    asyncio.run(_peer_disconnect(pubkey))


async def _peer_disconnect(pubkey: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.disconnect_peer(DisconnectPeerRequest(pubkey=pubkey))
        print_success(f"Disconnected from {pubkey}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
