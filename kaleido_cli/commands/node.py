"""Node lifecycle commands — wraps docker-compose."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from kaleido_sdk.rln import TakerRequest

from kaleido_cli.context import get_client, state
from kaleido_cli.docker_manager import (
    DEFAULT_BASE_DAEMON_PORT,
    DEFAULT_BASE_PEER_PORT,
    DEFAULT_SPAWN_DIR,
    DockerManager,
    SpawnConfig,
    SpawnManager,
    list_spawn_names,
)
from kaleido_cli.output import (
    is_interactive,
    is_json_mode,
    output_model,
    print_error,
    print_info,
    print_json,
    print_success,
    print_warning,
)

node_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help=(
        "Manage named RGB Lightning Node environments via Docker.\n\n"
        "[bold]Creating an environment:[/bold]\n"
        "  [cyan]kaleido node create[/cyan]          — wizard: configure ports, network\n\n"
        "[bold]Managing environments:[/bold]\n"
        "  [cyan]kaleido node list[/cyan]             — list all environments with their node URLs\n"
        "  [cyan]kaleido node up    <name>[/cyan]     — start containers\n"
        "  [cyan]kaleido node stop  <name>[/cyan]     — stop containers\n"
        "  [cyan]kaleido node down  <name>[/cyan]     — stop and remove containers\n"
        "  [cyan]kaleido node logs  <name>[/cyan]     — stream logs\n"
        "  [cyan]kaleido node ps    <name>[/cyan]     — show container status\n"
        "  [cyan]kaleido node clean <name>[/cyan]     — remove volumes (irreversible)\n\n"
        "[bold]Switching between nodes:[/bold]\n"
        "  [cyan]kaleido node use   <name>[/cyan]     — point node-url at node 1 of an environment\n"
        "  [cyan]kaleido node use   <name> --node 2[/cyan]  — point at a specific node index\n\n"
        "[bold]After starting:[/bold]\n"
        "  [cyan]kaleido node init[/cyan]             — initialize node wallet (once)\n"
        "  [cyan]kaleido node unlock[/cyan]           — unlock wallet after restart\n"
        "  [cyan]kaleido node shutdown[/cyan]        — gracefully shut down the node process\n"
        "  [cyan]kaleido node info[/cyan]             — check node reachability and details\n"
    ),
)

taker_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help="Taker-side swap operations — identity and swap acceptance.",
)

node_app.add_typer(taker_app, name="taker")

DEFAULT_BITCOIND_USER = "user"
DEFAULT_BITCOIND_PASS = "password"
DEFAULT_BITCOIND_HOST = "regtest-bitcoind.rgbtools.org"
DEFAULT_BITCOIND_PORT = 80
DEFAULT_INDEXER_URL = "electrum.rgbtools.org:50041"
DEFAULT_PROXY_ENDPOINT = "rpcs://proxy.iriswallet.com/0.2/json-rpc"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _base_spawn_dir() -> Path:
    """Base directory where named environments live."""
    d = state.config.spawn_dir
    return Path(d).expanduser().resolve() if d else DEFAULT_SPAWN_DIR


def _dm(name: str) -> DockerManager:
    """Return a DockerManager for the named environment."""
    return DockerManager(str(_base_spawn_dir() / name))


def _resolve_name(name: str | None) -> str:
    """If *name* is None/empty, auto-resolve from available environments."""
    if name:
        return name
    names = list_spawn_names(_base_spawn_dir())
    if not names:
        print_error("No environments found. Run 'kaleido node create' first.")
        raise typer.Exit(1)
    if len(names) == 1:
        print_info(f"Using environment: [bold]{names[0]}[/bold]")
        return names[0]
    print_error("Multiple environments exist — specify one:")
    for n in names:
        print_info(f"  kaleido node <cmd> {n}")
    print_info("See 'kaleido node list' for details.")
    raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Taker commands
# ---------------------------------------------------------------------------


@taker_app.command(
    "pubkey",
    epilog="  [cyan]kaleido node taker pubkey[/cyan]   Print the node's taker public key.",
)
def taker_pubkey() -> None:
    """Show the node's taker public key (used in swap operations)."""
    asyncio.run(_taker_pubkey())


async def _taker_pubkey() -> None:
    try:
        client = get_client(require_node=True)
        pubkey = await client.rln.get_taker_pubkey()
        if is_json_mode():
            print_json({"pubkey": pubkey})
        else:
            print_success(f"Taker pubkey: {pubkey}")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@taker_app.command(
    "whitelist",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Accept a swap offer from a maker:\n"
        "  [cyan]kaleido node taker whitelist '30/rgb:abc.../10/rgb:def.../...'[/cyan]"
    ),
)
def taker_whitelist(
    swapstring: Annotated[
        str | None,
        typer.Argument(help="Swap string to accept on the taker side."),
    ] = None,
) -> None:
    """Whitelist (accept) a swap string from a maker on the taker side."""
    resolved: str
    if swapstring is not None:
        resolved = swapstring
    elif is_interactive():
        resolved = typer.prompt("Swapstring")
    else:
        print_error("SWAPSTRING argument is required in non-interactive mode.")
        raise typer.Exit(1)

    asyncio.run(_taker_whitelist(resolved))


async def _taker_whitelist(swapstring: str) -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.whitelist_swap(TakerRequest(swapstring=swapstring))
        print_success("Swap whitelisted — taker accepted this offer.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


# ---------------------------------------------------------------------------
# Environment management
# ---------------------------------------------------------------------------


@node_app.command(
    "create",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Wizard with a new name:\n"
        "  [cyan]kaleido node create[/cyan]\n"
        "  [cyan]kaleido node create myenv[/cyan]\n\n"
        "  Then start with:\n"
        "  [cyan]kaleido node up myenv[/cyan]"
    ),
)
def node_create(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name (directory under spawn-dir). Prompted if omitted."),
    ] = None,
) -> None:
    """[bold]Wizard:[/bold] configure and generate a named compose environment."""
    from ..config import save_config

    print_info("\n  Kaleido Node Create Wizard")
    print_info("  " + "─" * 38)

    # ── Base spawn directory ─────────────────────────────────────────────────
    default_base = str(state.config.spawn_dir or DEFAULT_SPAWN_DIR)
    spawn_base_input = typer.prompt(
        "  Base directory for environments",
        default=default_base,
    )
    base = Path(spawn_base_input).expanduser().resolve()
    if str(base) != str(Path(default_base).expanduser().resolve()):
        state.config.spawn_dir = str(base)
        save_config(state.config)
        print_info(f"  Saved spawn-dir → {base}")

    # ── Environment name ─────────────────────────────────────────────────────
    resolved_name: str
    if name:
        resolved_name = name
    else:
        existing = list_spawn_names(base)
        if existing:
            print_info(
                "  Existing environments: " + ", ".join(f"[bold]{n}[/bold]" for n in existing)
            )
        resolved_name = typer.prompt("  Environment name", default="default")

    env_dir = base / resolved_name
    if (env_dir / "docker-compose.yml").exists():
        overwrite = typer.confirm(
            f"  Environment '{resolved_name}' already exists at {env_dir}. Overwrite?",
            default=False,
        )
        if not overwrite:
            print_info("  Aborted.")
            raise typer.Exit(0)

    # ── Node count ───────────────────────────────────────────────────────────
    count = typer.prompt("  How many RGB Lightning Nodes?", default=1, type=int)

    # ── Network ──────────────────────────────────────────────────────────────
    network = typer.prompt("  Bitcoin network", default=state.config.network or "regtest")

    # ── Node ports ───────────────────────────────────────────────────────────
    print_info("  ── Node ports ────────────────────────────────────────")
    end_d = DEFAULT_BASE_DAEMON_PORT + count - 1
    end_p = DEFAULT_BASE_PEER_PORT + count - 1
    daemon_base = typer.prompt(
        f"  Base daemon API port  ({DEFAULT_BASE_DAEMON_PORT}–{end_d})",
        default=DEFAULT_BASE_DAEMON_PORT,
        type=int,
    )
    peer_base = typer.prompt(
        f"  Base LDK peer port    ({DEFAULT_BASE_PEER_PORT}–{end_p})",
        default=DEFAULT_BASE_PEER_PORT,
        type=int,
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    print_info("")
    print_info("  ── Summary ───────────────────────────────────────────")
    print_info(f"  Name       : [bold]{resolved_name}[/bold]")
    print_info(f"  Directory  : {env_dir}")
    print_info(f"  Nodes      : {count}")
    print_info(f"  Network    : {network}")
    print_info(f"  Daemon API : localhost:{daemon_base}–{daemon_base + count - 1}")
    print_info(f"  LDK peers  : localhost:{peer_base}–{peer_base + count - 1}")
    print_info("")

    start_now = typer.confirm("  Start containers now?", default=True)

    # ── Generate + optionally start ───────────────────────────────────────────
    cfg = SpawnConfig(
        name=resolved_name,
        count=count,
        network=network,
        disable_authentication=True,
        base_daemon_port=daemon_base,
        base_peer_port=peer_base,
        spawn_base_dir=str(base),
    )

    manager = SpawnManager(cfg)
    rc = manager.spawn(start=start_now)

    if rc == 0:
        if not start_now:
            print_info(f"\n  Compose file written → {env_dir}")
            print_info(f"  Start with: [cyan]kaleido node up {resolved_name}[/cyan]")
        else:
            print_success(f"  Environment '{resolved_name}' started ({count} node(s)).")
            print_info("")
            for i, url in enumerate(manager.node_urls(), start=1):
                print_info(f"  Node {i} API : {url}")
            print_info("")
            print_info("  Next steps:")
            print_info(f"  1. [cyan]kaleido node use {resolved_name}[/cyan]")
            print_info("  2. [cyan]kaleido node init[/cyan]")
            print_info("  3. [cyan]kaleido node unlock[/cyan]")
    raise typer.Exit(rc)


@node_app.command("list")
def node_list() -> None:
    """List all named environments and their node URLs."""
    base = _base_spawn_dir()
    names = list_spawn_names(base)
    if not names:
        print_warning(f"No environments found in {base}")
        print_info("Run 'kaleido node create' to create one.")
        return
    print_info(f"Environments in [bold]{base}[/bold]:\n")
    for n in names:
        env_dir = base / n
        urls = _dm(n).node_urls()
        print_info(f"  [bold]{n}[/bold]  →  {env_dir}")
        if urls:
            for i, url in enumerate(urls, start=1):
                marker = "[green]●[/green]" if url == state.config.node_url else "[dim]○[/dim]"
                print_info(f"    {marker} node {i}: {url}")
        else:
            print_info("    [dim](no nodes detected in compose)[/dim]")


@node_app.command(
    "use",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Use node 1 of the default environment:\n"
        "  [cyan]kaleido node use default[/cyan]\n\n"
        "  Use node 2 of 'myenv' (multi-node setup):\n"
        "  [cyan]kaleido node use myenv --node 2[/cyan]\n\n"
        "  Then interact with it:\n"
        "  [cyan]kaleido node unlock[/cyan]\n"
        "  [cyan]kaleido wallet balance[/cyan]"
    ),
)
def node_use(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    node: Annotated[
        int,
        typer.Option("--node", "-n", help="1-based index of the node to select (default: 1)."),
    ] = 1,
) -> None:
    """Set node-url in config to point at a node in a named environment."""
    from ..config import save_config

    name = _resolve_name(name)
    urls = _dm(name).node_urls()
    if not urls:
        print_error(f"No nodes found in environment '{name}'. Is the compose file present?")
        raise typer.Exit(1)
    if node < 1 or node > len(urls):
        print_error(
            f"Node {node} does not exist in '{name}' — environment has {len(urls)} node(s)."
        )
        raise typer.Exit(1)
    url = urls[node - 1]
    state.config.node_url = url
    save_config(state.config)
    print_success(f"node-url → {url}")
    print_info("Run [cyan]kaleido node unlock[/cyan] to activate the wallet.")


# ---------------------------------------------------------------------------
# Docker lifecycle (scoped by environment name)
# ---------------------------------------------------------------------------


@node_app.command(
    "up",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  [cyan]kaleido node up default[/cyan]   Start the default environment\n"
        "  [cyan]kaleido node up myenv[/cyan]     Start a named environment\n"
        "  [cyan]kaleido node up[/cyan]           Auto-detect if only one environment exists"
    ),
)
def node_up(
    name: Annotated[
        str | None,
        typer.Argument(
            help="Environment name (from 'kaleido node list'). Auto-detected if only one exists."
        ),
    ] = None,
) -> None:
    """Start containers for a named environment (docker compose up -d)."""
    name = _resolve_name(name)
    dm = _dm(name)
    if not dm._validate():
        raise typer.Exit(1)
    print_info(f"Starting environment '{name}' …")
    rc = dm._run(["up", "-d"])
    if rc == 0:
        print_success(f"Environment '{name}' is up.")
    else:
        raise typer.Exit(rc)


@node_app.command(
    "stop",
    epilog=(
        "  [cyan]kaleido node stop <name>[/cyan]   Stop containers (data preserved).\n"
        "  [cyan]kaleido node stop[/cyan]           Auto-detect environment."
    ),
)
def node_stop(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
) -> None:
    """Stop running containers (without removing them)."""
    name = _resolve_name(name)
    rc = _dm(name).stop()
    if rc == 0:
        print_success(f"Environment '{name}' stopped.")
    else:
        raise typer.Exit(rc)


@node_app.command(
    "shutdown",
    epilog="  [cyan]kaleido node shutdown[/cyan]   Gracefully shut down the configured node process.",
)
def node_shutdown() -> None:
    """Gracefully shut down the configured node."""
    asyncio.run(_node_shutdown())


async def _node_shutdown() -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.shutdown()
        print_success("Node shutdown initiated.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_app.command(
    "down",
    epilog="  [cyan]kaleido node down <name>[/cyan]   Stop and remove containers + networks.",
)
def node_down(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
) -> None:
    """Stop and remove containers and networks (volumes are preserved)."""
    name = _resolve_name(name)
    rc = _dm(name).down()
    if rc == 0:
        print_success(f"Environment '{name}' containers removed.")
    else:
        raise typer.Exit(rc)


@node_app.command("ps")
def node_ps(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
) -> None:
    """List container status for an environment."""
    name = _resolve_name(name)
    _dm(name).ps()


@node_app.command(
    "logs",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Stream all logs:\n"
        "  [cyan]kaleido node logs default[/cyan]\n\n"
        "  Stream logs for one service:\n"
        "  [cyan]kaleido node logs myenv --service rgb_node_1[/cyan]\n\n"
        "  Print and exit:\n"
        "  [cyan]kaleido node logs default --no-follow[/cyan]"
    ),
)
def node_logs(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            "-s",
            help="Filter to a specific service (e.g. rgb_node_1, rgb_node_2).",
        ),
    ] = None,
    no_follow: Annotated[
        bool, typer.Option("--no-follow", help="Print existing logs and exit.")
    ] = False,
) -> None:
    """Stream logs from an environment's containers."""
    name = _resolve_name(name)
    _dm(name).logs(service=service, follow=not no_follow)


@node_app.command(
    "clean",
    epilog=(
        "  [red bold]Irreversible[/red bold] — deletes all data volumes.\n"
        "  [cyan]kaleido node clean <name> --yes[/cyan]   Skip confirmation."
    ),
)
def node_clean(
    name: Annotated[
        str | None,
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")] = False,
) -> None:
    """[red]Remove all data volumes for an environment (irreversible).[/red]"""
    name = _resolve_name(name)
    if not yes:
        confirmed = typer.confirm(
            f"Delete all blockchain & node data for environment '{name}'? This cannot be undone."
        )
        if not confirmed:
            print_info("Aborted.")
            raise typer.Exit(0)
    dm = _dm(name)
    dm.down()
    dm.clean()


# ---------------------------------------------------------------------------
# Node API (via SDK) — use node-url from config / --node-url flag
# ---------------------------------------------------------------------------


@node_app.command("info")
def node_info() -> None:
    """Display detailed node information."""
    asyncio.run(_node_info())


async def _node_info() -> None:
    try:
        client = get_client(require_node=True)
        info = await client.rln.get_node_info()
        net = await client.rln.get_network_info()
        output_model(info, title="Node Info")
        output_model(net, title="Network Info")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)


@node_app.command(
    "init",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Create a wallet password interactively:\n"
        "  [cyan]kaleido node init[/cyan]\n\n"
        "  Pass password directly:\n"
        "  [cyan]kaleido node init --password mysecret[/cyan]"
    ),
)
def node_init(
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            help="New wallet password. Prompted securely if omitted.",
            hide_input=True,
        ),
    ] = None,
    mnemonic: Annotated[
        str | None,
        typer.Option("--mnemonic", help="Optional mnemonic phrase to restore during init."),
    ] = None,
) -> None:
    """Initialize a new node wallet (run once after first start)."""
    resolved_password: str
    if password is not None:
        resolved_password = password
    else:
        resolved_password = typer.prompt(
            "Create a new wallet password", hide_input=True, confirmation_prompt=True
        )
    asyncio.run(_node_init(resolved_password, mnemonic))


async def _node_init(password: str, mnemonic: str | None) -> None:
    from kaleido_sdk.rln import InitRequest

    try:
        client = get_client(require_node=True)
        response = await client.rln.init_wallet(InitRequest(password=password, mnemonic=mnemonic))
        print_success("Wallet initialized.")
        output_model(response, title="Init Response")
    except Exception as e:
        print_error(f"Error initializing wallet: {e}")
        raise typer.Exit(1)


@node_app.command(
    "unlock",
    epilog=(
        "[bold]Examples[/bold]\n\n"
        "  Simple unlock (uses rgbtools.org defaults):\n"
        "  [cyan]kaleido node unlock[/cyan]\n\n"
        "  Override bitcoind credentials:\n"
        "  [cyan]kaleido node unlock --bitcoind-user alice --bitcoind-pass hunter2[/cyan]\n\n"
        "  Full custom override:\n"
        "  [cyan]kaleido node unlock \\\n"
        "    --bitcoind-host 192.168.1.100 --bitcoind-port 18443 \\\n"
        "    --bitcoind-user alice --bitcoind-pass hunter2 \\\n"
        "    --indexer-url tcp://192.168.1.100:50001 \\\n"
        "    --proxy-endpoint http://192.168.1.100:3000[/cyan]\n\n"
        "  With Lightning peer announcement:\n"
        "  [cyan]kaleido node unlock --announce-alias 'MyNode' --announce-address '203.0.113.42:9735'[/cyan]"
    ),
)
def node_unlock(
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            "-p",
            help="Wallet password. Prompted securely if omitted.",
            hide_input=True,
        ),
    ] = None,
    bitcoind_pass: Annotated[
        str,
        typer.Option(
            "--bitcoind-pass",
            help="bitcoind RPC password.",
            hide_input=True,
        ),
    ] = DEFAULT_BITCOIND_PASS,
    bitcoind_user: Annotated[
        str,
        typer.Option("--bitcoind-user", help="bitcoind RPC username."),
    ] = DEFAULT_BITCOIND_USER,
    bitcoind_host: Annotated[
        str,
        typer.Option("--bitcoind-host", help="bitcoind RPC host."),
    ] = DEFAULT_BITCOIND_HOST,
    bitcoind_port: Annotated[
        int,
        typer.Option("--bitcoind-port", help="bitcoind RPC port."),
    ] = DEFAULT_BITCOIND_PORT,
    indexer_url: Annotated[
        str,
        typer.Option("--indexer-url", help="Electrs indexer URL."),
    ] = DEFAULT_INDEXER_URL,
    proxy_endpoint: Annotated[
        str,
        typer.Option("--proxy-endpoint", help="RGB proxy endpoint."),
    ] = DEFAULT_PROXY_ENDPOINT,
    announce_alias: Annotated[
        str,
        typer.Option("--announce-alias", help="Lightning peer alias to announce."),
    ] = "",
    announce_address: Annotated[
        list[str],
        typer.Option(
            "--announce-address",
            help="Public address(es) for Lightning peer discovery (can be repeated).",
        ),
    ] = [],
) -> None:
    """Unlock the node wallet."""
    resolved_password: str
    if password is not None:
        resolved_password = password
    else:
        resolved_password = typer.prompt("Wallet password", hide_input=True)

    if is_interactive():
        use_defaults = typer.confirm(
            "Use default rgbtools.org services (bitcoind, indexer, proxy)?", default=True
        )
        if not use_defaults:
            bitcoind_user = typer.prompt("bitcoind RPC username", default=bitcoind_user)
            bitcoind_pass = typer.prompt(
                "bitcoind RPC password", default=bitcoind_pass, hide_input=True
            )
            bitcoind_host = typer.prompt("bitcoind RPC host", default=bitcoind_host)
            bitcoind_port = typer.prompt("bitcoind RPC port", default=bitcoind_port, type=int)
            indexer_url = typer.prompt("Electrs indexer URL", default=indexer_url)
            proxy_endpoint = typer.prompt("RGB proxy endpoint", default=proxy_endpoint)
        else:
            bitcoind_user = DEFAULT_BITCOIND_USER
            bitcoind_pass = DEFAULT_BITCOIND_PASS
            bitcoind_host = DEFAULT_BITCOIND_HOST
            bitcoind_port = DEFAULT_BITCOIND_PORT
            indexer_url = DEFAULT_INDEXER_URL
            proxy_endpoint = DEFAULT_PROXY_ENDPOINT
        raw = typer.prompt("[OPTIONAL] Lightning announce alias (Enter to skip)", default="")
        if raw.strip():
            announce_alias = raw.strip()
        raw = typer.prompt("[OPTIONAL] Lightning announce address (Enter to skip)", default="")
        if raw.strip():
            announce_address = [raw.strip()]

    asyncio.run(
        _node_unlock(
            password=resolved_password,
            bitcoind_user=bitcoind_user,
            bitcoind_pass=bitcoind_pass,
            bitcoind_host=bitcoind_host,
            bitcoind_port=bitcoind_port,
            indexer_url=indexer_url,
            proxy_endpoint=proxy_endpoint,
            announce_alias=announce_alias,
            announce_addresses=announce_address,
        )
    )


async def _node_unlock(
    password: str,
    bitcoind_user: str,
    bitcoind_pass: str,
    bitcoind_host: str,
    bitcoind_port: int,
    indexer_url: str,
    proxy_endpoint: str,
    announce_alias: str,
    announce_addresses: list[str],
) -> None:
    from kaleido_sdk.rln import UnlockRequest

    try:
        client = get_client(require_node=True)
        req = UnlockRequest(
            password=password,
            bitcoind_rpc_username=bitcoind_user,
            bitcoind_rpc_password=bitcoind_pass,
            bitcoind_rpc_host=bitcoind_host,
            bitcoind_rpc_port=bitcoind_port,
            indexer_url=indexer_url,
            proxy_endpoint=proxy_endpoint,
            announce_alias=announce_alias,
            announce_addresses=announce_addresses,
        )

        await client.rln.unlock_wallet(req)
        print_success("Wallet unlocked.")

        # Show what was configured
        if bitcoind_pass:
            print_info(f"Connected to bitcoind: {bitcoind_user}@{bitcoind_host}:{bitcoind_port}")
        if indexer_url:
            print_info(f"Connected to indexer: {indexer_url}")
        if proxy_endpoint:
            print_info(f"Connected to RGB proxy: {proxy_endpoint}")
        if announce_alias:
            print_info(f"Announcing as: [bold]{announce_alias}[/bold]")
        if announce_addresses:
            for addr in announce_addresses:
                print_info(f"Announcing address: {addr}")
    except Exception as e:
        print_error(f"Error unlocking wallet: {e}")
        raise typer.Exit(1)


@node_app.command("lock")
def node_lock() -> None:
    """Lock the node wallet."""
    asyncio.run(_node_lock())


async def _node_lock() -> None:
    try:
        client = get_client(require_node=True)
        await client.rln.lock_wallet()
        print_success("Wallet locked.")
    except Exception as e:
        print_error(f"Error: {e}")
        raise typer.Exit(1)
