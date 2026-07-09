"""Atomic swap commands."""

from __future__ import annotations

import asyncio
from typing import Annotated

import typer
from kaleido_sdk import (
    ConfirmSwapResponse,
    PairQuoteResponse,
    SwapResponse,
    SwapStatusRequest,
    SwapStatusResponse,
)
from kaleido_sdk.rln import (
    TakerRequest,
)

from kaleido_cli.context import get_client
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_model,
    print_error,
    print_info,
    print_json,
    print_success,
)
from kaleido_cli.utils.errors import raise_cli_error
from kaleido_cli.utils.prompts import resolve_required_text
from kaleido_cli.utils.quotes import resolve_and_fetch_quote
from kaleido_cli.utils.swaps import (
    confirm_swap_request,
    decode_swapstring,
    swap_request_from_quote,
    validate_swapstring_against_quote,
    validate_swapstring_against_swap,
)

swap_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help=(
        "Atomic swap flow against the Kaleidoswap maker server, using your local node as taker.\n\n"
        "For low-level local node swaps, use [cyan]kaleido node swap ...[/cyan]."
    ),
)
atomic_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Atomic swap flow against the Kaleidoswap maker server, using your local node as taker.",
)

swap_app.add_typer(atomic_app, name="atomic")


def _confirm_quote_or_exit(quote: PairQuoteResponse, *, title: str, yes: bool) -> None:
    """Show a quote and require explicit acceptance before continuing."""
    if is_json_mode():
        if not yes:
            print_error("--yes is required in non-interactive mode to accept the quoted price.")
            raise typer.Exit(1)
        return

    output_model(quote, title=title)

    if is_interactive():
        if yes:
            return
        if not typer.confirm("Proceed with this quote?", default=True):
            print_error("Swap cancelled before initialization.")
            raise typer.Exit(0)
        return

    if not yes:
        print_error("--yes is required in non-interactive mode to accept the quoted price.")
        raise typer.Exit(1)


@atomic_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Initialize an atomic swap from a live quote:\n"
        "  [cyan]kaleido swap atomic init BTC/USDT --to-amount 5[/cyan]\n\n"
        "[dim]After init, you can whitelist explicitly, or let execute do it for you:[/dim]\n"
        "[cyan]kaleido node swap whitelist --swapstring '<swapstring>'[/cyan]\n"
        "[cyan]kaleido swap atomic execute --swapstring '<swapstring>' "
        "--taker-pubkey <pubkey> --payment-hash <payment-hash>[/cyan]\n"
        "[cyan]kaleido swap atomic execute --auto-whitelist --swapstring '<swapstring>' "
        "--taker-pubkey <pubkey> --payment-hash <payment-hash>[/cyan]"
    ),
)
def atomic_init(
    pair: Annotated[
        str | None, typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT.")
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
            help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Accept the displayed quote without prompting. Required in non-interactive mode.",
        ),
    ] = False,
) -> None:
    """Initialize an atomic swap against the maker server using a live quote."""
    asyncio.run(
        _atomic_init(
            pair,
            from_amount,
            to_amount,
            from_layer,
            to_layer,
            yes,
        )
    )


async def _atomic_init(
    pair: str | None,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str | None,
    to_layer: str | None,
    yes: bool,
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
        )
        quote = resolved_quote.quote
        _confirm_quote_or_exit(quote, title=f"Quote — {resolved_quote.inputs.pair}", yes=yes)
        resp: SwapResponse = await client.maker.init_swap(swap_request_from_quote(quote))
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            print_success(f"Atomic swap initialized: {resp.payment_hash}")
            output_model(resp, title="Atomic Swap Init")
            print_info("Next step: choose one of these two flows.")
            print_info(
                "Flow 1 (manual): whitelist first on your local taker node, then execute against the maker server."
            )
            print_info(f"  kaleido node swap whitelist --swapstring '{resp.swapstring}'")
            print_info(
                f"  kaleido swap atomic execute --swapstring '{resp.swapstring}' "
                f"--taker-pubkey <pubkey> --payment-hash {resp.payment_hash}"
            )
            print_info(
                "Flow 2 (automatic): let atomic execute whitelist on your local node first, then execute against the maker server."
            )
            print_info(
                f"  kaleido swap atomic execute --auto-whitelist --swapstring '{resp.swapstring}' "
                f"--taker-pubkey <pubkey> --payment-hash {resp.payment_hash}"
            )
    except typer.Exit:
        raise
    except Exception as e:
        raise_cli_error(e)


@atomic_app.command(
    "execute",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Execute a previously initialized atomic swap:\n"
        "  [cyan]kaleido swap atomic execute --swapstring '<swapstring>' "
        "--taker-pubkey 03ab... --payment-hash deadbeef...[/cyan]\n\n"
        "  Auto-whitelist before executing:\n"
        "  [cyan]kaleido swap atomic execute --auto-whitelist --swapstring '<swapstring>' "
        "--taker-pubkey 03ab... --payment-hash deadbeef...[/cyan]\n\n"
        "[dim]Use the taker node pubkey from 'kaleido node swap pubkey' or your node's pubkey.[/dim]"
    ),
)
def atomic_execute(
    swapstring: Annotated[
        str | None, typer.Option("--swapstring", help="Swap string returned by atomic init.")
    ] = None,
    taker_pubkey: Annotated[
        str | None, typer.Option("--taker-pubkey", help="Taker node pubkey.")
    ] = None,
    payment_hash: Annotated[
        str | None, typer.Option("--payment-hash", help="Payment hash returned by atomic init.")
    ] = None,
    auto_whitelist: Annotated[
        bool,
        typer.Option(
            "--auto-whitelist",
            help="Whitelist the swap on the local taker node before executing it.",
        ),
    ] = False,
) -> None:
    """Execute an atomic swap against the maker server."""
    resolved_swapstring = resolve_required_text(swapstring, "Swap string", "--swapstring")
    resolved_taker_pubkey = resolve_required_text(taker_pubkey, "Taker pubkey", "--taker-pubkey")
    resolved_payment_hash = resolve_required_text(payment_hash, "Payment hash", "--payment-hash")
    if is_interactive() and not auto_whitelist:
        auto_whitelist = typer.confirm(
            "Auto-whitelist on the local taker node before executing?",
            default=False,
        )
    asyncio.run(
        _atomic_execute(
            resolved_swapstring, resolved_taker_pubkey, resolved_payment_hash, auto_whitelist
        )
    )


async def _atomic_execute(
    swapstring: str,
    taker_pubkey: str,
    payment_hash: str,
    auto_whitelist: bool,
) -> None:
    try:
        client = get_client(require_node=auto_whitelist)
        if auto_whitelist:
            decoded = decode_swapstring(swapstring)
            status = await client.maker.get_atomic_swap_status(
                SwapStatusRequest(payment_hash=payment_hash)
            )
            if status.swap is None:
                print_error(
                    "Maker returned no swap payload for --payment-hash; refusing to auto-whitelist."
                )
                raise typer.Exit(1)
            try:
                validate_swapstring_against_swap(
                    decoded,
                    status.swap,
                    payment_hash=payment_hash,
                )
            except ValueError as exc:
                print_error(f"Auto-whitelist validation failed: {exc}")
                raise typer.Exit(1)
            await client.rln.whitelist_swap(TakerRequest(swapstring=swapstring))
        resp: ConfirmSwapResponse = await client.maker.execute_swap(
            confirm_swap_request(
                swapstring=swapstring,
                taker_pubkey=taker_pubkey,
                payment_hash=payment_hash,
            )
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            if auto_whitelist:
                print_success("Atomic swap whitelisted on taker node")
            print_success("Atomic swap execution submitted")
            output_model(resp, title="Atomic Swap Execute")
    except Exception as e:
        raise_cli_error(e)


@atomic_app.command(
    "status",
    epilog="  [cyan]kaleido swap atomic status <payment-hash>[/cyan]",
)
def atomic_status(
    payment_hash: Annotated[str, typer.Argument(help="Atomic swap payment hash.")],
) -> None:
    """Check the status of an atomic swap against the maker server."""
    asyncio.run(_atomic_status(payment_hash))


async def _atomic_status(payment_hash: str) -> None:
    try:
        client = get_client()
        resp: SwapStatusResponse = await client.maker.get_atomic_swap_status(
            SwapStatusRequest(payment_hash=payment_hash)
        )
        if is_json_mode():
            print_json(resp.model_dump())
        else:
            output_model(resp, title=f"Atomic Swap — {payment_hash[:16]}…")
    except Exception as e:
        raise_cli_error(e)


@atomic_app.command(
    "run",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Run an atomic swap in one command using your local taker node:\n"
        "  [cyan]kaleido swap atomic run BTC/USDT --to-amount 5[/cyan]\n\n"
        "  Non-interactive flow with an explicit taker pubkey:\n"
        "  [cyan]kaleido swap atomic run BTC/USDT --from-amount 0.001 --from-layer BTC_LN "
        "--to-layer RGB_LN --taker-pubkey 03ab... --yes[/cyan]\n\n"
        "[dim]This wrapper automates atomic init, local taker whitelist, and atomic execute.[/dim]"
    ),
)
def atomic_run(
    pair: Annotated[
        str | None, typer.Argument(help="Trading pair in BASE/QUOTE format, e.g. BTC/USDT.")
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
            help="Source layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    to_layer: Annotated[
        str | None,
        typer.Option(
            "--to-layer",
            help="Destination layer: BTC_L1, BTC_LN, RGB_L1, RGB_LN. Defaults from the requested pair direction.",
        ),
    ] = None,
    taker_pubkey: Annotated[
        str | None,
        typer.Option(
            "--taker-pubkey", help="Taker node pubkey. Defaults to the local node taker pubkey."
        ),
    ] = None,
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            "-y",
            help="Accept the displayed quote and skip later confirmations. Required in non-interactive mode.",
        ),
    ] = False,
) -> None:
    """Run an atomic swap end-to-end using the local node as taker."""
    asyncio.run(
        _atomic_run(
            pair,
            from_amount,
            to_amount,
            from_layer,
            to_layer,
            taker_pubkey,
            yes,
        )
    )


async def _atomic_run(
    pair: str | None,
    from_amount: str | None,
    to_amount: str | None,
    from_layer: str | None,
    to_layer: str | None,
    taker_pubkey_override: str | None,
    yes: bool,
) -> None:
    try:
        client = get_client(require_node=True)
        resolved_quote = await resolve_and_fetch_quote(
            client,
            pair=pair,
            from_amount=from_amount,
            to_amount=to_amount,
            from_layer=from_layer,
            to_layer=to_layer,
        )
        quote = resolved_quote.quote
        _confirm_quote_or_exit(quote, title=f"Quote — {resolved_quote.inputs.pair}", yes=yes)
        init_resp: SwapResponse = await client.maker.init_swap(swap_request_from_quote(quote))
        decoded_swap = decode_swapstring(init_resp.swapstring)
        validate_swapstring_against_quote(
            decoded_swap,
            quote,
            payment_hash=init_resp.payment_hash,
        )
        resolved_taker_pubkey = taker_pubkey_override or await client.rln.get_taker_pubkey()

        if not yes and is_interactive():
            confirmed = typer.confirm(
                "Whitelist this atomic swap on the local taker node and execute it now?",
                default=True,
            )
            if not confirmed:
                print_error("Swap cancelled after atomic init.")
                raise typer.Exit(0)

        await client.rln.whitelist_swap(TakerRequest(swapstring=init_resp.swapstring))
        execute_resp: ConfirmSwapResponse = await client.maker.execute_swap(
            confirm_swap_request(
                swapstring=init_resp.swapstring,
                taker_pubkey=resolved_taker_pubkey,
                payment_hash=init_resp.payment_hash,
            )
        )

        if is_json_mode():
            print_json(
                {
                    "init": init_resp.model_dump(),
                    "whitelisted": True,
                    "taker_pubkey": resolved_taker_pubkey,
                    "execute": execute_resp.model_dump(),
                }
            )
        else:
            print_success(f"Atomic swap initialized: {init_resp.payment_hash}")
            output_model(init_resp, title="Atomic Swap Init")
            print_success("Swap whitelisted on local taker node")
            print_success("Atomic swap execution submitted")
            output_model(
                {
                    "taker_pubkey": resolved_taker_pubkey,
                    **execute_resp.model_dump(),
                },
                title="Atomic Swap Execute",
            )
    except typer.Exit:
        raise
    except Exception as e:
        raise_cli_error(e)
