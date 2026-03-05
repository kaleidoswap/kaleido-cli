"""Node lifecycle commands — wraps docker-compose."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, Optional

import typer

from ..app import get_client, state
from ..docker_manager import (
    DEFAULT_BASE_DAEMON_PORT,
    DEFAULT_BASE_PEER_PORT,
    DEFAULT_SPAWN_DIR,
    DockerManager,
    InfraConfig,
    SpawnConfig,
    SpawnManager,
    list_spawn_names,
)
from ..output import output_model, print_error, print_info, print_success, print_warning

node_app = typer.Typer(
    no_args_is_help=True,
    rich_markup_mode="rich",
    help=(
        "Manage named RGB Lightning Node environments via Docker.\n\n"
        "[bold]Creating an environment:[/bold]\n"
        "  [cyan]kaleido node create[/cyan]          — wizard: configure ports, network, infra\n\n"
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
        "  [cyan]kaleido node status[/cyan]           — check node reachability\n"
    ),
)


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


def _resolve_name(name: Optional[str]) -> str:
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
        Optional[str],
        typer.Argument(
            help="Environment name (directory under spawn-dir). Prompted if omitted."
        ),
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
    if not name:
        existing = list_spawn_names(base)
        if existing:
            print_info(
                "  Existing environments: "
                + ", ".join(f"[bold]{n}[/bold]" for n in existing)
            )
        name = typer.prompt("  Environment name", default="default")

    env_dir = base / name
    if (env_dir / "docker-compose.yml").exists():
        overwrite = typer.confirm(
            f"  Environment '{name}' already exists at {env_dir}. Overwrite?",
            default=False,
        )
        if not overwrite:
            print_info("  Aborted.")
            raise typer.Exit(0)

    # ── Node count ───────────────────────────────────────────────────────────
    count = typer.prompt("  How many RGB Lightning Nodes?", default=1, type=int)

    # ── Network ──────────────────────────────────────────────────────────────
    network = typer.prompt(
        "  Bitcoin network", default=state.config.network or "regtest"
    )

    # ── Full infra stack ─────────────────────────────────────────────────────
    with_infra = typer.confirm(
        "  Include full infra stack (bitcoind + electrs + RGB proxy)?",
        default=False,
    )

    infra = InfraConfig()
    if with_infra:
        print_info("  ── bitcoind ──────────────────────────────────────────")
        infra.btc_rpc_user = typer.prompt("  RPC username", default="kaleido")
        raw_pass = typer.prompt(
            "  RPC password (leave blank to auto-generate)",
            default="",
            hide_input=True,
        )
        if raw_pass:
            infra.btc_rpc_pass = raw_pass
        else:
            infra.btc_rpc_pass = _os.urandom(16).hex()
            print_info(f"  Generated RPC password: [bold]{infra.btc_rpc_pass}[/bold]")
        infra.bitcoind_rpc_port = typer.prompt(
            "  bitcoind RPC port", default=18443, type=int
        )

        print_info("  ── electrs ───────────────────────────────────────────")
        infra.electrs_port = typer.prompt("  electrs port", default=50001, type=int)

        print_info("  ── RGB proxy ─────────────────────────────────────────")
        infra.proxy_port = typer.prompt("  RGB proxy port", default=3000, type=int)

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
    print_info(f"  Name       : [bold]{name}[/bold]")
    print_info(f"  Directory  : {env_dir}")
    print_info(f"  Nodes      : {count}")
    print_info(f"  Network    : {network}")
    print_info(f"  Daemon API : localhost:{daemon_base}–{daemon_base + count - 1}")
    print_info(f"  LDK peers  : localhost:{peer_base}–{peer_base + count - 1}")
    print_info("")

    start_now = typer.confirm("  Start containers now?", default=True)

    # ── Generate + optionally start ───────────────────────────────────────────
    cfg = SpawnConfig(
        name=name,
        count=count,
        network=network,
        disable_authentication=True,
        base_daemon_port=daemon_base,
        base_peer_port=peer_base,
        with_infra=with_infra,
        infra=infra,
        spawn_base_dir=str(base),
    )

    manager = SpawnManager(cfg)
    rc = manager.spawn(start=start_now)

    if rc == 0:
        if not start_now:
            print_info(f"\n  Compose file written → {env_dir}")
            print_info(f"  Start with: [cyan]kaleido node up {name}[/cyan]")
        else:
            print_success(f"  Environment '{name}' started ({count} node(s)).")
            print_info("")
            for i, url in enumerate(manager.node_urls(), start=1):
                print_info(f"  Node {i} API : {url}")
            print_info("")
            print_info("  Next steps:")
            print_info(f"  1. [cyan]kaleido node use {name}[/cyan]")
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
                marker = (
                    "[green]●[/green]"
                    if url == state.config.node_url
                    else "[dim]○[/dim]"
                )
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
        Optional[str],
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    node: Annotated[
        int,
        typer.Option(
            "--node", "-n", help="1-based index of the node to select (default: 1)."
        ),
    ] = 1,
) -> None:
    """Set node-url in config to point at a node in a named environment."""
    from ..config import save_config

    name = _resolve_name(name)
    urls = _dm(name).node_urls()
    if not urls:
        print_error(
            f"No nodes found in environment '{name}'. Is the compose file present?"
        )
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
        Optional[str],
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
        Optional[str],
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
    "down",
    epilog="  [cyan]kaleido node down <name>[/cyan]   Stop and remove containers + networks.",
)
def node_down(
    name: Annotated[
        Optional[str],
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
        Optional[str],
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
        "  [cyan]kaleido node logs default --service bitcoind[/cyan]\n"
        "  [cyan]kaleido node logs myenv --service rgb_node_1[/cyan]\n\n"
        "  Print and exit:\n"
        "  [cyan]kaleido node logs default --no-follow[/cyan]"
    ),
)
def node_logs(
    name: Annotated[
        Optional[str],
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    service: Annotated[
        Optional[str],
        typer.Option(
            "--service",
            "-s",
            help="Filter to a specific service (e.g. bitcoind, rgb_node_1).",
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
        Optional[str],
        typer.Argument(help="Environment name. Auto-detected if only one exists."),
    ] = None,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation prompt.")
    ] = False,
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


@node_app.command("status")
def node_status() -> None:
    """Check node health and display basic info."""
    asyncio.run(_node_status())


async def _node_status() -> None:
    try:
        client = get_client(require_node=True)
        info = await client.rln.get_node_info()
        output_model(info, title="Node Info")
    except Exception as e:
        print_error(f"Could not reach node: {e}")
        raise typer.Exit(1)


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
        "  Interactive prompt:\n"
        "  [cyan]kaleido node init[/cyan]\n\n"
        "  Pass password directly:\n"
        "  [cyan]kaleido node init --password mysecret[/cyan]"
    ),
)
def node_init(
    password: Annotated[
        Optional[str],
        typer.Option(
            "--password",
            "-p",
            help="Wallet password. Prompted securely if omitted.",
            hide_input=True,
        ),
    ] = None,
) -> None:
    """Initialize a new node wallet (run once after first start)."""
    if password is None:
        password = typer.prompt(
            "Wallet password", hide_input=True, confirmation_prompt=True
        )
    asyncio.run(_node_init(password))


async def _node_init(password: str) -> None:
    from kaleidoswap_sdk.rln import InitRequest

    try:
        client = get_client(require_node=True)
        response = await client.rln.init_wallet(InitRequest(password=password))
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
        Optional[str],
        typer.Option(
            "--password",
            "-p",
            help="Wallet password. Prompted securely if omitted.",
            hide_input=True,
        ),
    ] = None,
    bitcoind_pass: Annotated[
        Optional[str],
        typer.Option(
            "--bitcoind-pass",
            help="bitcoind RPC password (default: password).",
            hide_input=True,
        ),
    ] = None,
    bitcoind_user: Annotated[
        Optional[str],
        typer.Option("--bitcoind-user", help="bitcoind RPC username (default: user)."),
    ] = None,
    bitcoind_host: Annotated[
        Optional[str],
        typer.Option(
            "--bitcoind-host",
            help="bitcoind RPC host (default: regtest-bitcoind.rgbtools.org).",
        ),
    ] = None,
    bitcoind_port: Annotated[
        Optional[int],
        typer.Option("--bitcoind-port", help="bitcoind RPC port (default: 80)."),
    ] = None,
    indexer_url: Annotated[
        Optional[str],
        typer.Option(
            "--indexer-url",
            help="Electrs indexer URL (default: electrum.rgbtools.org:50041).",
        ),
    ] = None,
    proxy_endpoint: Annotated[
        Optional[str],
        typer.Option(
            "--proxy-endpoint",
            help="RGB proxy endpoint (default: rpcs://proxy.iriswallet.com/0.2/json-rpc).",
        ),
    ] = None,
    announce_alias: Annotated[
        Optional[str],
        typer.Option("--announce-alias", help="Lightning peer alias to announce."),
    ] = None,
    announce_address: Annotated[
        Optional[list[str]],
        typer.Option(
            "--announce-address",
            help="Public address(es) for Lightning peer discovery (can be repeated).",
        ),
    ] = None,
) -> None:
    """Unlock the node wallet."""
    if password is None:
        password = typer.prompt("Wallet password", hide_input=True)

    # Server requires ALL fields — apply defaults for rgbtools.org public services
    bitcoind_user = bitcoind_user or "user"
    bitcoind_pass = bitcoind_pass or "password"
    bitcoind_host = bitcoind_host or "regtest-bitcoind.rgbtools.org"
    bitcoind_port = bitcoind_port if bitcoind_port is not None else 80
    indexer_url = indexer_url or "electrum.rgbtools.org:50041"
    proxy_endpoint = proxy_endpoint or "rpcs://proxy.iriswallet.com/0.2/json-rpc"
    announce_alias = announce_alias or ""
    announce_address = announce_address or []

    asyncio.run(
        _node_unlock(
            password=password,
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
    from kaleidoswap_sdk.rln import UnlockRequest

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
            print_info(
                f"Connected to bitcoind: {bitcoind_user}@{bitcoind_host}:{bitcoind_port}"
            )
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
