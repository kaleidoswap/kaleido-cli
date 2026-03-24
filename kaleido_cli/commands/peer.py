"""Peer connection commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    ConnectPeerRequest,
    DisconnectPeerRequest,
    ListPeersResponse,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_collection,
    print_error,
    print_json,
    print_success,
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
        output_collection(
            "Peers", [p.model_dump() for p in (resp.peers or [])], item_title="Peer — {index}"
        )
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
        str | None,
        typer.Argument(help="Peer address in [green]pubkey@host:port[/green] format."),
    ] = None,
) -> None:
    """Connect to a peer."""
    resolved_peer: str
    if peer is not None:
        resolved_peer = peer
    elif is_interactive():
        resolved_peer = typer.prompt("Peer (pubkey@host:port)")
    else:
        print_error("PEER argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_peer_connect(resolved_peer))


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
        str | None,
        typer.Argument(help="Full pubkey of the peer to disconnect."),
    ] = None,
) -> None:
    """Disconnect from a peer."""
    resolved_pubkey: str
    if pubkey is not None:
        resolved_pubkey = pubkey
    elif is_interactive():
        resolved_pubkey = typer.prompt("Peer pubkey (from 'kaleido peer list')")
    else:
        print_error("PUBKEY argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_peer_disconnect(resolved_pubkey))


async def _peer_disconnect(pubkey: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.disconnect_peer(DisconnectPeerRequest(peer_pubkey=pubkey))
        print_success(f"Disconnected from {pubkey}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
