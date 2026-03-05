"""Wallet commands — BTC balance, addresses, transactions."""

from __future__ import annotations

import asyncio
from typing import Annotated, Optional

import typer

from ..app import get_client
from ..output import (
    is_json_mode,
    output_model,
    print_error,
    print_json,
    print_success,
    print_table,
)
from kaleidoswap_sdk.rln import (
    AddressResponse,
    BackupRequest,
    BtcBalanceResponse,
    CreateUtxosRequest,
    ListTransactionsRequest,
    ListTransactionsResponse,
    ListUnspentsRequest,
    ListUnspentsResponse,
    SendBtcRequest,
    SendBtcResponse,
)

wallet_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="BTC wallet operations — balance, addresses, send, UTXOs, transactions, backup.",
)


@wallet_app.command(
    "address",
    epilog="  [cyan]kaleido wallet address[/cyan]   Get a fresh on-chain deposit address.",
)
def wallet_address() -> None:
    """Get a new on-chain BTC deposit address."""
    asyncio.run(_wallet_address())


async def _wallet_address() -> None:
    try:
        client = get_client(require_node=True)
        resp: AddressResponse = await client.rln.get_address()
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Address: {resp.address}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "balance",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  [cyan]kaleido wallet balance[/cyan]              Full balance (syncs first)\n"
        "  [cyan]kaleido wallet balance --skip-sync[/cyan]  Use cached balance (faster)"
    ),
)
def wallet_balance(
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync", help="Skip blockchain sync and return cached balance."
        ),
    ] = False,
) -> None:
    """Show BTC wallet balance (vanilla + colored UTXOs)."""
    asyncio.run(_wallet_balance(skip_sync))


async def _wallet_balance(skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        resp: BtcBalanceResponse = await client.rln.get_btc_balance(skip_sync=skip_sync)
        if is_json_mode():
            print_json(resp.model_dump())
            return
        output_model(resp, title="BTC Balance")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "send",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Send 50 000 sats at default fee rate:\n"
        "  [cyan]kaleido wallet send 50000 bc1q...[/cyan]\n\n"
        "  Send with a specific fee rate:\n"
        "  [cyan]kaleido wallet send 50000 bc1q... --fee-rate 5.0[/cyan]\n\n"
        "  Skip blockchain sync before sending:\n"
        "  [cyan]kaleido wallet send 50000 bc1q... --skip-sync[/cyan]"
    ),
)
def wallet_send(
    amount: Annotated[int, typer.Argument(help="Amount to send in satoshis.")],
    address: Annotated[str, typer.Argument(help="Destination Bitcoin address.")],
    fee_rate: Annotated[
        Optional[float],
        typer.Option(
            "--fee-rate", help="Fee rate in sat/vbyte. Uses node default if omitted."
        ),
    ] = None,
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync", help="Skip blockchain sync before sending."
        ),
    ] = False,
) -> None:
    """Send on-chain BTC."""
    asyncio.run(_wallet_send(amount, address, fee_rate, skip_sync))


async def _wallet_send(amount: int, address: str, fee_rate: float | None, skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        body = SendBtcRequest(amount=amount, address=address, fee_rate=fee_rate, skip_sync=skip_sync)
        resp: SendBtcResponse = await client.rln.send_btc(body)
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Sent! TXID: {resp.txid}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "utxos",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  [cyan]kaleido wallet utxos[/cyan]              List UTXOs (syncs first)\n"
        "  [cyan]kaleido wallet utxos --skip-sync[/cyan]  Use cached UTXO data (faster)"
    ),
)
def wallet_utxos(
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync", help="Skip blockchain sync and return cached UTXOs."
        ),
    ] = False,
) -> None:
    """List unspent transaction outputs."""
    asyncio.run(_wallet_utxos(skip_sync))


async def _wallet_utxos(skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        resp: ListUnspentsResponse = await client.rln.list_unspents(
            ListUnspentsRequest(skip_sync=skip_sync)
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [
                u.utxo.outpoint if u.utxo else "-",
                u.utxo.btc_amount if u.utxo else "-",
                u.rgb_allocations,
            ]
            for u in (resp.unspents or [])
        ]
        print_table("UTXOs", ["Outpoint", "BTC Amount (sat)", "RGB Allocations"], rows)
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "create-utxos",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Create 5 UTXOs of default size:\n"
        "  [cyan]kaleido wallet create-utxos[/cyan]\n\n"
        "  Create 10 UTXOs of 3000 sats each:\n"
        "  [cyan]kaleido wallet create-utxos --num 10 --size 3000[/cyan]\n\n"
        "  Create UTXOs up to a total limit with custom fee rate:\n"
        "  [cyan]kaleido wallet create-utxos --up-to --num 10 --size 1000 --fee-rate 2.5[/cyan]\n\n"
        "[dim]RGB assets require colored UTXOs to hold allocations.[/dim]"
    ),
)
def wallet_create_utxos(
    num: Annotated[
        Optional[int], typer.Option("--num", "-n", help="Number of UTXOs to create.")
    ] = None,
    size: Annotated[
        Optional[int], typer.Option("--size", help="Size of each UTXO in satoshis.")
    ] = None,
    up_to: Annotated[
        bool,
        typer.Option(
            "--up-to", help="If true, num represents total limit instead of count."
        ),
    ] = False,
    fee_rate: Annotated[
        Optional[float],
        typer.Option("--fee-rate", help="On-chain fee rate in sat/vbyte."),
    ] = None,
    skip_sync: Annotated[
        bool,
        typer.Option("--skip-sync", help="Skip blockchain sync before creating UTXOs."),
    ] = False,
) -> None:
    """Create UTXOs for RGB asset operations."""
    asyncio.run(
        _wallet_create_utxos(
            num=num,
            size=size,
            up_to=up_to,
            fee_rate=fee_rate,
            skip_sync=skip_sync,
        )
    )


async def _wallet_create_utxos(
    num: int | None,
    size: int | None,
    up_to: bool,
    fee_rate: float | None,
    skip_sync: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        body = CreateUtxosRequest(
            num=num,
            size=size,
            up_to=up_to,
            fee_rate=fee_rate,
            skip_sync=skip_sync,
        )
        await client.rln.create_utxos(body)
        created_msg = f"{num} UTXO(s)" if num else "UTXOs"
        print_success(f"Created {created_msg}.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "transactions",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  [cyan]kaleido wallet transactions[/cyan]              Full transaction list (syncs first)\n"
        "  [cyan]kaleido wallet transactions --skip-sync[/cyan]  Use cached transactions (faster)"
    ),
)
def wallet_transactions(
    skip_sync: Annotated[
        bool,
        typer.Option(
            "--skip-sync", help="Skip blockchain sync and return cached transactions."
        ),
    ] = False,
) -> None:
    """List on-chain transactions."""
    asyncio.run(_wallet_transactions(skip_sync))


async def _wallet_transactions(skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        resp: ListTransactionsResponse = await client.rln.list_transactions(
            ListTransactionsRequest(skip_sync=skip_sync)
        )
        if is_json_mode():
            print_json(resp.model_dump())
            return
        rows = [
            [t.txid, t.received, t.sent, t.fee, t.confirmation_time]
            for t in (resp.transactions or [])
        ]
        print_table(
            "Transactions",
            ["TXID", "Received (sat)", "Sent (sat)", "Fee (sat)", "Confirmed"],
            rows,
        )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "backup",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Interactive password prompt:\n"
        "  [cyan]kaleido wallet backup ~/my-backup.zip[/cyan]\n\n"
        "  Non-interactive:\n"
        "  [cyan]kaleido wallet backup /backups/node.zip --password mysecret[/cyan]"
    ),
)
def wallet_backup(
    path: Annotated[
        str, typer.Argument(help="Destination path for the backup archive.")
    ],
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            "-p",
            hide_input=True,
            help="Backup encryption password. Prompted if omitted.",
        ),
    ] = None,
) -> None:
    """Backup node wallet data."""
    if password is None:
        password = typer.prompt(
            "Backup password", hide_input=True, confirmation_prompt=True
        )
    asyncio.run(_wallet_backup(path, password))


async def _wallet_backup(path: str, password: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.backup(BackupRequest(backup_path=path, password=password))
        print_success(f"Backup saved to {path}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
