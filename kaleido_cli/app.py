"""Main Typer application — global state, callback, and sub-command registration."""

from __future__ import annotations

from typing import Annotated

import typer

from .config import load_config
from .context import state
from .output import set_json_mode

# ---------------------------------------------------------------------------
# Root app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="kaleido",
    help=(
        "Manage RGB Lightning Nodes and interact with the Kaleidoswap protocol.\n\n"
        "[bold]Global flags[/bold] can be placed before any sub-command:\n\n"
        "  [cyan]kaleido --node-url http://localhost:3001 wallet balance[/cyan]\n"
        "  [cyan]kaleido --json market pairs[/cyan]\n\n"
        "[bold]Environment variables[/bold]\n\n"
        "  [green]KALEIDO_NODE_URL[/green]  RLN node URL (overrides config)\n"
        "  [green]KALEIDO_API_URL[/green]   Kaleidoswap API URL (overrides config)\n"
    ),
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    rich_markup_mode="rich",
)


@app.callback()
def _root(
    json_output: Annotated[
        bool, typer.Option("--json", help="Output raw JSON instead of formatted tables.")
    ] = False,
    node_url: Annotated[
        str | None,
        typer.Option(
            "--node-url",
            help="RGB Lightning Node base URL. Overrides config + env.",
            envvar="KALEIDO_NODE_URL",
            show_default="config / KALEIDO_NODE_URL",
        ),
    ] = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help="Kaleidoswap maker API URL. Overrides config + env.",
            envvar="KALEIDO_API_URL",
            show_default="config / KALEIDO_API_URL",
        ),
    ] = None,
) -> None:
    state.config = load_config()
    state.node_url = node_url
    state.api_url = api_url
    set_json_mode(json_output)


# ---------------------------------------------------------------------------
# Register sub-command groups
# ---------------------------------------------------------------------------

from .commands.asset import asset_app  # noqa: E402
from .commands.channel import channel_app  # noqa: E402
from .commands.config_cmd import config_app  # noqa: E402
from .commands.market import market_app  # noqa: E402
from .commands.node import node_app  # noqa: E402
from .commands.payment import payment_app  # noqa: E402
from .commands.peer import peer_app  # noqa: E402
from .commands.swap import swap_app  # noqa: E402
from .commands.wallet import wallet_app  # noqa: E402

app.add_typer(
    node_app, name="node", help="Manage the RLN node via Docker (start, stop, spawn, init…)."
)
app.add_typer(
    wallet_app, name="wallet", help="BTC wallet — balance, addresses, send, UTXOs, backup."
)
app.add_typer(asset_app, name="asset", help="RGB assets — list, issue, send, invoices, transfers.")
app.add_typer(channel_app, name="channel", help="Lightning channels — list, open, close.")
app.add_typer(peer_app, name="peer", help="Peer connections — list, connect, disconnect.")
app.add_typer(
    payment_app, name="payment", help="Lightning payments — pay, invoice, decode, status."
)
app.add_typer(market_app, name="market", help="Kaleidoswap market data — assets, pairs, quotes.")
app.add_typer(swap_app, name="swap", help="Atomic RGB+LN swaps — quote, execute, history.")
app.add_typer(config_app, name="config", help="CLI configuration stored in ~/.kaleido/config.json.")


def main() -> None:
    app()
