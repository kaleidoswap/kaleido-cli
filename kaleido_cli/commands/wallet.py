"""Wallet commands — BTC balance, addresses, transactions."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk.rln import (
    AddressResponse,
    BackupRequest,
    BtcBalanceResponse,
    ChangePasswordRequest,
    CreateUtxosRequest,
    EstimateFeeRequest,
    EstimateFeeResponse,
    ListTransactionsRequest,
    ListTransactionsResponse,
    ListUnspentsRequest,
    ListUnspentsResponse,
    RestoreRequest,
    SendBtcRequest,
    SendBtcResponse,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_collection,
    output_model,
    print_error,
    print_json,
    print_success,
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
        typer.Option("--skip-sync", help="Skip blockchain sync and return cached balance."),
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
    amount: Annotated[int | None, typer.Argument(help="Amount to send in satoshis.")] = None,
    address: Annotated[str | None, typer.Argument(help="Destination Bitcoin address.")] = None,
    fee_rate: Annotated[
        int,
        typer.Option("--fee-rate", help="Fee rate in sat/vbyte."),
    ] = 1,
    skip_sync: Annotated[
        bool,
        typer.Option("--skip-sync", help="Skip blockchain sync before sending."),
    ] = False,
) -> None:
    """Send on-chain BTC."""
    resolved_amount: int
    if amount is not None:
        resolved_amount = amount
    elif is_interactive():
        resolved_amount = typer.prompt("Amount to send (satoshis)", type=int)
    else:
        print_error("AMOUNT argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_address: str
    if address is not None:
        resolved_address = address
    elif is_interactive():
        resolved_address = typer.prompt("Destination Bitcoin address")
    else:
        print_error("ADDRESS argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_wallet_send(resolved_amount, resolved_address, fee_rate, skip_sync))


async def _wallet_send(amount: int, address: str, fee_rate: int, skip_sync: bool) -> None:
    try:
        client = get_client(require_node=True)
        body = SendBtcRequest(
            amount=amount,
            address=address,
            fee_rate=fee_rate,
            skip_sync=skip_sync,
        )
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
        typer.Option("--skip-sync", help="Skip blockchain sync and return cached UTXOs."),
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
        items = []
        for u in resp.unspents or []:
            items.append(
                {
                    "outpoint": u.utxo.outpoint if u.utxo else None,
                    "btc_amount_sat": u.utxo.btc_amount if u.utxo else None,
                    "rgb_allocations": u.rgb_allocations,
                }
            )
        output_collection("UTXOs", items, item_title="UTXO — {index}")
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
        int | None, typer.Option("--num", "-n", help="Number of UTXOs to create.")
    ] = None,
    size: Annotated[
        int | None, typer.Option("--size", help="Size of each UTXO in satoshis.")
    ] = None,
    up_to: Annotated[
        bool,
        typer.Option("--up-to", help="If true, num represents total limit instead of count."),
    ] = False,
    fee_rate: Annotated[
        int,
        typer.Option("--fee-rate", help="On-chain fee rate in sat/vbyte."),
    ] = 1,
    skip_sync: Annotated[
        bool,
        typer.Option("--skip-sync", help="Skip blockchain sync before creating UTXOs."),
    ] = False,
) -> None:
    """Create UTXOs for RGB asset operations."""
    if is_interactive():
        if num is None:
            raw = typer.prompt(
                "[OPTIONAL] Number of UTXOs to create (Enter for node default)", default=""
            )
            if raw.strip():
                num = int(raw.strip())
        if size is None:
            raw = typer.prompt(
                "[OPTIONAL] Size of each UTXO in satoshis (Enter for node default)", default=""
            )
            if raw.strip():
                size = int(raw.strip())

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
    fee_rate: int,
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
        typer.Option("--skip-sync", help="Skip blockchain sync and return cached transactions."),
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
        output_collection(
            "Transactions",
            [t.model_dump() for t in (resp.transactions or [])],
            item_title="Transaction — {index}",
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
        str | None, typer.Argument(help="Destination path for the backup archive.")
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            hide_input=True,
            help="Backup encryption password. Prompted if omitted.",
        ),
    ] = None,
) -> None:
    """Backup node wallet data."""
    resolved_path: str
    if path is not None:
        resolved_path = path
    elif is_interactive():
        resolved_path = typer.prompt("Destination path for the backup archive")
    else:
        print_error("PATH argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_password: str
    if password is not None:
        resolved_password = password
    else:
        resolved_password = typer.prompt(
            "Backup password", hide_input=True, confirmation_prompt=True
        )

    asyncio.run(_wallet_backup(resolved_path, resolved_password))


async def _wallet_backup(path: str, password: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.backup(BackupRequest(backup_path=path, password=password))
        print_success(f"Backup saved to {path}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "restore",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Interactive password prompt:\n"
        "  [cyan]kaleido wallet restore ~/my-backup.zip[/cyan]\n\n"
        "  Non-interactive:\n"
        "  [cyan]kaleido wallet restore /backups/node.zip --password mysecret[/cyan]\n\n"
        "[bold dim]Warning:[/bold dim] Restore will overwrite the current node data."
    ),
)
def wallet_restore(
    path: Annotated[
        str | None, typer.Argument(help="Path to the backup archive to restore from.")
    ] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            hide_input=True,
            help="Backup decryption password. Prompted if omitted.",
        ),
    ] = None,
) -> None:
    """Restore node wallet data from a backup."""
    resolved_path: str
    if path is not None:
        resolved_path = path
    elif is_interactive():
        resolved_path = typer.prompt("Path to the backup archive")
    else:
        print_error("PATH argument is required in non-interactive mode.")
        raise typer.Exit(1)

    resolved_password: str
    if password is not None:
        resolved_password = password
    else:
        resolved_password = typer.prompt("Backup password", hide_input=True)

    asyncio.run(_wallet_restore(resolved_path, resolved_password))


async def _wallet_restore(path: str, password: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.restore(RestoreRequest(backup_path=path, password=password))
        print_success(f"Restored from {path}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "change-password",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Interactive prompts:\n"
        "  [cyan]kaleido wallet change-password[/cyan]\n\n"
        "  Non-interactive:\n"
        "  [cyan]kaleido wallet change-password --old-password old --new-password new[/cyan]"
    ),
)
def wallet_change_password(
    old_password: Annotated[
        str | None,
        typer.Option("--old-password", hide_input=True, help="Current wallet password."),
    ] = None,
    new_password: Annotated[
        str | None,
        typer.Option("--new-password", hide_input=True, help="New wallet password."),
    ] = None,
) -> None:
    """Change the node wallet password."""
    if old_password is None:
        old_password = typer.prompt("Current password", hide_input=True)
    if new_password is None:
        new_password = typer.prompt("New password", hide_input=True, confirmation_prompt=True)

    assert old_password is not None
    assert new_password is not None
    asyncio.run(_wallet_change_password(old_password, new_password))


async def _wallet_change_password(old_password: str, new_password: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.change_password(
            ChangePasswordRequest(old_password=old_password, new_password=new_password)
        )
        print_success("Password changed successfully.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@wallet_app.command(
    "estimate-fee",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Estimate fee for confirmation within 6 blocks:\n"
        "  [cyan]kaleido wallet estimate-fee --blocks 6[/cyan]\n\n"
        "  Fast (1 block) confirmation target:\n"
        "  [cyan]kaleido wallet estimate-fee --blocks 1[/cyan]"
    ),
)
def wallet_estimate_fee(
    blocks: Annotated[
        int,
        typer.Option("--blocks", "-b", help="Target confirmation in this many blocks."),
    ] = 6,
) -> None:
    """Estimate the on-chain fee rate for a target confirmation window."""
    asyncio.run(_wallet_estimate_fee(blocks))


async def _wallet_estimate_fee(blocks: int) -> None:
    try:
        client = get_client(require_node=True)
        resp: EstimateFeeResponse = await client.rln.estimate_fee(EstimateFeeRequest(blocks=blocks))
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(
                f"Estimated fee rate: {resp.fee_rate} sat/vbyte (target: {blocks} blocks)"
            )
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
