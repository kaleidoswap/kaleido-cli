"""Main Typer application — global state, callback, and sub-command registration."""

from __future__ import annotations

from typing import Annotated

import typer

from .config import load_config
from .context import state
from .onboarding import SetupMode, run_setup
from .output import set_agent_mode, set_json_mode

# ---------------------------------------------------------------------------
# Root app
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="kaleido",
    help=(
        "Manage RGB Lightning Nodes and interact with the Kaleidoswap protocol.\n\n"
        "[bold]First time here?[/bold]\n\n"
        "  [cyan]kaleido setup[/cyan]               Guided setup for market-only or local-node use\n\n"
        "[bold]Global flags[/bold] can be placed before any sub-command:\n\n"
        "  [cyan]kaleido --node-url http://localhost:3001 wallet balance[/cyan]\n"
        "  [cyan]kaleido --json market pairs[/cyan]\n"
        "  [cyan]kaleido --agent channel open --peer 03ab...@host:9735 --capacity 100000[/cyan]\n\n"
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
    agent: Annotated[
        bool,
        typer.Option(
            "--agent",
            help="Non-interactive mode for scripted/agent use — skips wizard prompts.",
        ),
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
    set_agent_mode(agent)


@app.command(
    "setup",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Interactive first-run setup:\n"
        "  [cyan]kaleido setup[/cyan]\n\n"
        "  Market-only defaults without prompts:\n"
        "  [cyan]kaleido setup --mode market --defaults[/cyan]\n\n"
        "  Create and start a local node environment with defaults:\n"
        "  [cyan]kaleido setup --mode local --create-node --defaults[/cyan]"
    ),
)
def setup_command(
    mode: Annotated[
        SetupMode | None,
        typer.Option("--mode", help="Setup profile: 'market' or 'local'."),
    ] = None,
    defaults: Annotated[
        bool,
        typer.Option(
            "--defaults",
            help="Use saved/default values for any omitted options instead of prompting.",
        ),
    ] = False,
    api_url: Annotated[
        str | None,
        typer.Option("--api-url", help="Kaleidoswap API URL to save in config."),
    ] = None,
    network: Annotated[
        str | None,
        typer.Option("--network", help="Bitcoin network to save in config."),
    ] = None,
    node_url: Annotated[
        str | None,
        typer.Option("--node-url", help="RGB Lightning Node URL to save in config."),
    ] = None,
    create_node: Annotated[
        bool | None,
        typer.Option(
            "--create-node/--no-create-node",
            help="Create a local Docker node environment during setup.",
        ),
    ] = None,
    spawn_dir: Annotated[
        str | None,
        typer.Option("--spawn-dir", help="Base directory for local node environments."),
    ] = None,
    env_name: Annotated[
        str | None,
        typer.Option("--env-name", help="Environment name when creating a local node."),
    ] = None,
    node_count: Annotated[
        int | None,
        typer.Option("--node-count", min=1, help="Number of nodes to create."),
    ] = None,
    start: Annotated[
        bool | None,
        typer.Option("--start/--no-start", help="Start the node environment after creating it."),
    ] = None,
) -> None:
    """Guide first-time configuration and optionally create a local node environment."""
    run_setup(
        mode=mode,
        defaults=defaults,
        api_url=api_url,
        network=network,
        node_url=node_url,
        create_node=create_node,
        spawn_dir=spawn_dir,
        env_name=env_name,
        node_count=node_count,
        start=start,
    )


# ---------------------------------------------------------------------------
# Register sub-command groups
# ---------------------------------------------------------------------------

from .commands.asset import asset_app  # noqa: E402
from .commands.channel import channel_app  # noqa: E402
from .commands.config_cmd import config_app  # noqa: E402
from .commands.lsp import lsp_app  # noqa: E402
from .commands.maker import maker_app  # noqa: E402
from .commands.taker import taker_app  # noqa: E402
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
    wallet_app, name="wallet", help="BTC wallet — balance, addresses, send, UTXOs, backup, restore."
)
app.add_typer(asset_app, name="asset", help="RGB assets — list, issue (NIA/CFA/UDA), send, invoices, transfers.")
app.add_typer(channel_app, name="channel", help="Lightning channels — list, open, close.")
app.add_typer(peer_app, name="peer", help="Peer connections — list, connect, disconnect.")
app.add_typer(
    payment_app, name="payment", help="Lightning payments — pay, invoice, keysend, decode, status."
)
app.add_typer(market_app, name="market", help="Kaleidoswap market data — assets, pairs, routes, quotes, analytics.")
app.add_typer(
    swap_app,
    name="swap",
    help="Swap flows grouped by scope: maker order flow, maker atomic flow, and local node flow.",
)
app.add_typer(lsp_app, name="lsp", help="LSP (Lightning Service Provider) — info, channel orders, fees.")
app.add_typer(maker_app, name="maker", help="Maker swap operations — init and execute atomic swaps.")
app.add_typer(taker_app, name="taker", help="Taker swap operations — pubkey and swap whitelisting.")
app.add_typer(config_app, name="config", help="CLI configuration stored in ~/.kaleido/config.json.")


def main() -> None:
    app()
