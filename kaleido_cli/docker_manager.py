"""Docker Compose wrapper for RLN node lifecycle management."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .config import DEFAULT_NETWORK, normalize_network_name
from .output import print_error, print_info, print_success, print_warning

COMPOSE_FILE = "docker-compose.yml"

RLN_IMAGE_REPO = "kaleidoswap/rgb-lightning-node"
RLN_IMAGE = f"{RLN_IMAGE_REPO}:0.10.0"

DEFAULT_BASE_DAEMON_PORT = 3001
DEFAULT_BASE_PEER_PORT = 9735
DEFAULT_NETWORK_NAME = "kaleidoswap-network"
DEFAULT_SPAWN_DIR = Path.home() / ".kaleido"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def list_spawn_names(base_dir: Path) -> list[str]:
    """Return the names of all environments found under *base_dir*.

    An environment is a sub-directory that contains a ``docker-compose.yml``.
    """
    if not base_dir.exists():
        return []
    return sorted(d.name for d in base_dir.iterdir() if d.is_dir() and (d / COMPOSE_FILE).exists())


def port_in_use(port: int) -> bool:
    """True if *port* cannot be bound on the IPv4 or IPv6 wildcard address."""
    for family, host in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.bind((host, port))
        except OSError as exc:
            if family == socket.AF_INET6 and exc.errno == getattr(socket, "EAFNOSUPPORT", None):
                continue
            return True
    return False


def reserved_ports(base_dir: Path, exclude: str | None = None) -> set[int]:
    """Host ports published by existing environments under *base_dir*, running or not."""
    ports: set[int] = set()
    for name in list_spawn_names(base_dir):
        if name == exclude:
            continue
        try:
            compose = yaml.safe_load((base_dir / name / COMPOSE_FILE).read_text()) or {}
        except (OSError, yaml.YAMLError):
            continue
        for service in (compose.get("services") or {}).values():
            for mapping in (service or {}).get("ports") or []:
                host = str(mapping).split(":")[-2] if ":" in str(mapping) else str(mapping)
                if host.isdigit():
                    ports.add(int(host))
    return ports


def find_free_base_ports(
    count: int,
    base_dir: Path,
    exclude_env: str | None = None,
    daemon_base: int = DEFAULT_BASE_DAEMON_PORT,
    peer_base: int = DEFAULT_BASE_PEER_PORT,
    max_tries: int = 100,
) -> tuple[int, int]:
    """First (daemon_base, peer_base) pair whose *count* consecutive ports are all free."""
    taken = reserved_ports(base_dir, exclude=exclude_env)

    def block_free(start: int) -> bool:
        return all(p not in taken and not port_in_use(p) for p in range(start, start + count))

    def first_free(start: int) -> int:
        for offset in range(max_tries):
            candidate = start + offset * count
            if block_free(candidate):
                return candidate
        raise RuntimeError(f"No free port block of {count} found from {start}")

    return first_free(daemon_base), first_free(peer_base)


def container_user() -> str | None:
    """On Linux, run as the invoking user so bind-mounted data dirs stay writable.

    The image runs as uid 1000; Docker Desktop maps bind-mount ownership, plain
    Linux Docker does not.
    """
    if not sys.platform.startswith("linux") or os.getuid() == 0:
        return None
    return f"{os.getuid()}:{os.getgid()}"


def upgrade_compose(compose_path: Path, image: str = RLN_IMAGE) -> list[tuple[str, str]]:
    """Point every RLN service in *compose_path* at *image*.

    Returns ``(service, old_image)`` for each service that changed. Also drops the
    ``linux/amd64`` pin older CLIs wrote (the image is multi-arch) and creates the
    bind-mounted data dirs so a non-root container can write to them.
    """
    compose = yaml.safe_load(compose_path.read_text()) or {}
    changed: list[tuple[str, str]] = []
    user = container_user()
    for name, service in (compose.get("services") or {}).items():
        old = str((service or {}).get("image", ""))
        if not old.startswith(RLN_IMAGE_REPO):
            continue
        dirty = False
        if old != image:
            service["image"] = image
            changed.append((name, old))
            dirty = True
        if service.pop("platform", None) is not None:
            dirty = True
        if user and service.get("user") != user:
            service["user"] = user
            dirty = True
        for volume in service.get("volumes") or []:
            host = str(volume).split(":")[0]
            if host.startswith("."):
                (compose_path.parent / host).mkdir(parents=True, exist_ok=True)
        if dirty and (name, old) not in changed:
            changed.append((name, old))
    if changed:
        compose_path.write_text(yaml.dump(compose, default_flow_style=False, sort_keys=False))
    return changed


def compose_images(compose_path: Path) -> set[str]:
    """RLN images referenced by *compose_path*."""
    try:
        compose = yaml.safe_load(compose_path.read_text()) or {}
    except (OSError, yaml.YAMLError):
        return set()
    return {
        str(svc.get("image"))
        for svc in (compose.get("services") or {}).values()
        if svc and str(svc.get("image", "")).startswith(RLN_IMAGE_REPO)
    }


# ---------------------------------------------------------------------------
# Spawn configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class NodeConfig:
    """Per-node port / volume overrides for a spawned RGB Lightning Node."""

    index: int  # 0-based
    daemon_port: int = 0  # 0 = auto → base_daemon_port + index
    peer_port: int = 0  # 0 = auto → base_peer_port + index
    data_dir: str = ""  # "" = auto → <spawn_dir>/volumes/dataldk<index>
    base_daemon_port: int = DEFAULT_BASE_DAEMON_PORT
    base_peer_port: int = DEFAULT_BASE_PEER_PORT

    def resolved_daemon_port(self) -> int:
        return self.daemon_port or (self.base_daemon_port + self.index)

    def resolved_peer_port(self) -> int:
        return self.peer_port or (self.base_peer_port + self.index)

    def resolved_data_dir(self, spawn_dir: Path) -> Path:
        if self.data_dir:
            return Path(self.data_dir).expanduser().resolve()
        return spawn_dir / "volumes" / f"dataldk{self.index}"


@dataclass
class SpawnConfig:
    """Configuration for a named set of RGB Lightning Nodes."""

    # Environment identity
    name: str = "default"
    spawn_base_dir: str = ""  # "" → ~/.kaleido  (env lives at base/name)

    count: int = 1
    network: str = DEFAULT_NETWORK
    # Docker network
    network_name: str = DEFAULT_NETWORK_NAME
    network_external: bool = False
    # Node options
    disable_authentication: bool = True
    base_daemon_port: int = DEFAULT_BASE_DAEMON_PORT
    base_peer_port: int = DEFAULT_BASE_PEER_PORT
    # Optional per-node port / path overrides keyed by 0-based index
    node_overrides: dict[int, NodeConfig] = field(default_factory=dict)

    def resolved_base_dir(self) -> Path:
        """The root spawn directory (parent of all environments)."""
        if self.spawn_base_dir:
            return Path(self.spawn_base_dir).expanduser().resolve()
        return DEFAULT_SPAWN_DIR

    def resolved_spawn_dir(self) -> Path:
        """The directory for *this* environment (base / name)."""
        return self.resolved_base_dir() / self.name

    def get_nodes(self) -> list[NodeConfig]:
        return [
            self.node_overrides.get(
                i,
                NodeConfig(
                    index=i,
                    base_daemon_port=self.base_daemon_port,
                    base_peer_port=self.base_peer_port,
                ),
            )
            for i in range(self.count)
        ]


class DockerManager:
    def __init__(self, compose_dir: str) -> None:
        self.compose_dir = Path(compose_dir).expanduser().resolve()

    def _validate(self) -> bool:
        if not self.compose_dir.exists():
            print_error(f"Environment directory not found: {self.compose_dir}")
            print_info("Run 'kaleido node create' to create it.")
            return False
        if not (self.compose_dir / COMPOSE_FILE).exists():
            print_error(f"No {COMPOSE_FILE} found in {self.compose_dir}")
            print_info("Run 'kaleido node create' to regenerate it.")
            return False
        if shutil.which("docker") is None:
            print_error("Docker is not installed or not in PATH.")
            return False
        return True

    def _run(self, args: list[str], *, stream: bool = False) -> int:
        cmd = ["docker", "compose", "--file", COMPOSE_FILE] + args
        try:
            if stream:
                result = subprocess.run(cmd, cwd=self.compose_dir)
            else:
                result = subprocess.run(cmd, cwd=self.compose_dir, capture_output=False)
            return result.returncode
        except KeyboardInterrupt:
            return 0

    # ------------------------------------------------------------------
    # Public commands
    # ------------------------------------------------------------------

    def stop(self) -> int:
        if not self._validate():
            return 1
        print_info("Stopping services …")
        return self._run(["stop"])

    def down(self) -> int:
        if not self._validate():
            return 1
        print_info("Stopping and removing containers …")
        return self._run(["down"])

    def logs(self, service: str | None = None, follow: bool = True) -> int:
        if not self._validate():
            return 1
        args = ["logs"]
        if follow:
            args.append("-f")
        if service:
            args.append(service)
        return self._run(args, stream=True)

    def ps(self) -> int:
        if not self._validate():
            return 1
        return self._run(["ps"])

    def node_urls(self) -> list[str]:
        """Read the compose file and return the HTTP URL for each rgb_node_* service."""
        compose_path = self.compose_dir / COMPOSE_FILE
        if not compose_path.exists():
            return []
        doc = yaml.safe_load(compose_path.read_text())
        urls: list[str] = []
        services = doc.get("services", {})
        i = 1
        while True:
            svc = services.get(f"rgb_node_{i}")
            if svc is None:
                break
            # port mapping can be "HOST:CONTAINER" or "BIND:HOST:CONTAINER"
            ports = svc.get("ports", [])
            if ports:
                host_port = str(ports[0]).split(":")[-2]
                urls.append(f"http://localhost:{host_port}")
            i += 1
        return urls

    def clean(self) -> int:
        if not self._validate():
            return 1
        removed = False
        for candidate in self.compose_dir.iterdir():
            if candidate.is_dir():
                print_info(f"Removing {candidate}")
                shutil.rmtree(candidate)
                removed = True
        if not removed:
            print_warning("No data directories found — nothing to clean.")
        else:
            print_info("Data removed.")
        return 0


# ---------------------------------------------------------------------------
# SpawnManager — generates a compose file and manages spawned RLN nodes
# ---------------------------------------------------------------------------


class SpawnManager(DockerManager):
    """Generates a docker-compose.yml for a named environment and manages its lifecycle."""

    def __init__(self, config: SpawnConfig) -> None:
        self.spawn_config = config
        super().__init__(str(config.resolved_spawn_dir()))

    # Override _validate — before generate_compose() the dir may not exist yet
    def _validate(self) -> bool:
        if shutil.which("docker") is None:
            print_error("Docker is not installed or not in PATH.")
            return False
        compose_path = self.compose_dir / COMPOSE_FILE
        if not compose_path.exists():
            print_error(f"No {COMPOSE_FILE} found in {self.compose_dir}")
            print_info("Run 'kaleido node create' to generate it.")
            return False
        return True

    # ------------------------------------------------------------------
    # Compose generation
    # ------------------------------------------------------------------

    def generate_compose(self) -> Path:
        """Write docker-compose.yml from SpawnConfig. Returns the compose file path."""
        spawn_dir = self.spawn_config.resolved_spawn_dir()
        spawn_dir.mkdir(parents=True, exist_ok=True)

        compose_dict = self._build_compose_dict(spawn_dir)
        compose_path = spawn_dir / COMPOSE_FILE
        compose_path.write_text(yaml.dump(compose_dict, default_flow_style=False, sort_keys=False))
        print_success(f"Compose file written to {compose_path}")
        return compose_path

    def _build_compose_dict(self, spawn_dir: Path) -> dict:
        cfg = self.spawn_config
        services: dict = {}

        # ----------------------------------------------------------------
        # RGB Lightning Nodes
        # ----------------------------------------------------------------
        for node in cfg.get_nodes():
            idx = node.index
            daemon_port = node.resolved_daemon_port()
            peer_port = node.resolved_peer_port()
            container_data = f"/tmp/kaleidoswap/dataldk{idx}"
            host_data = f"./volumes/dataldk{idx}"

            cmd_parts = [
                f"{container_data}/",
                f"--daemon-listening-port {daemon_port}",
                f"--ldk-peer-listening-port {peer_port}",
            ]
            if cfg.disable_authentication:
                cmd_parts.append("--disable-authentication")
            rln_network = normalize_network_name(cfg.network)
            cmd_parts.append(f"--network {rln_network}")

            service: dict = {
                "image": RLN_IMAGE,
                "command": " ".join(cmd_parts),
                "networks": [cfg.network_name],
                "ports": [
                    f"{daemon_port}:{daemon_port}",
                    f"{peer_port}:{peer_port}",
                ],
                "volumes": [f"{host_data}:{container_data}"],
                "environment": {
                    "APP_ENV": "${APP_ENV:-test}",
                    "NETWORK": "${NETWORK:-" + rln_network + "}",
                    "DAEMON_PORT": daemon_port,
                },
                "healthcheck": {
                    "test": [
                        "CMD",
                        "curl",
                        "-f",
                        f"http://localhost:{daemon_port}/nodeinfo",
                    ],
                    "interval": "10s",
                    "timeout": "10s",
                    "retries": 3,
                    "start_period": "10s",
                },
                "extra_hosts": ["myproxy.local:host-gateway"],
                "stop_grace_period": "1m",
                "stop_signal": "SIGTERM",
            }

            if user := container_user():
                service["user"] = user
            (spawn_dir / host_data).mkdir(parents=True, exist_ok=True)

            services[f"rgb_node_{idx + 1}"] = service

        network_def: dict = {}
        if cfg.network_external:
            network_def["external"] = True
        # else: let Docker create the bridge automatically (no extra keys needed)

        return {
            "services": services,
            "networks": {cfg.network_name: network_def},
        }

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def spawn(self, start: bool = True) -> int:
        """Generate compose file and optionally start the containers."""
        self.generate_compose()
        if not start:
            return 0
        if shutil.which("docker") is None:
            print_error("Docker is not installed or not in PATH.")
            return 1
        n = self.spawn_config.count
        label = f"{n} node(s)"
        print_info(f"Starting {label} …")
        return self._run(["up", "-d"])

    def node_urls(self) -> list[str]:
        """Return the HTTP URLs of each spawned node."""
        return [
            f"http://localhost:{node.resolved_daemon_port()}"
            for node in self.spawn_config.get_nodes()
        ]


def get_spawn_manager(config: SpawnConfig) -> SpawnManager:
    return SpawnManager(config)
