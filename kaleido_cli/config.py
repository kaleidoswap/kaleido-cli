"""CLI configuration management — stored in ~/.kaleido/config.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".kaleido"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API_URL = "https://api.signet.kaleidoswap.com/"
DEFAULT_NODE_URL = "http://localhost:3001"
DEFAULT_NETWORK = "mutinynet"

RLN_SIGNET_CUSTOM_NETWORK = "signetcustom"
MUTINYNET_ALIASES = {"mutinynet", "signetcustom", "customsignet"}

DEFAULT_BITCOIND_RPC_USERNAME = "user"
DEFAULT_BITCOIND_RPC_PASSWORD = "default_password"
DEFAULT_BITCOIND_RPC_HOST = "bitcoind.signet.kaleidoswap.com"
DEFAULT_BITCOIND_RPC_PORT = 38332
DEFAULT_INDEXER_URL = "electrum.signet.kaleidoswap.com:60601"
DEFAULT_PROXY_ENDPOINT = "rpcs://proxy.iriswallet.com/0.2/json-rpc"

DEFAULT_REGTEST_BITCOIND_RPC_USERNAME = "user"
DEFAULT_REGTEST_BITCOIND_RPC_PASSWORD = "password"
DEFAULT_REGTEST_BITCOIND_RPC_HOST = "regtest-bitcoind.rgbtools.org"
DEFAULT_REGTEST_BITCOIND_RPC_PORT = 80
DEFAULT_REGTEST_INDEXER_URL = "electrum.rgbtools.org:50041"
DEFAULT_REGTEST_PROXY_ENDPOINT = "rpcs://proxy.iriswallet.com/0.2/json-rpc"


def normalize_network_name(network: str) -> str:
    """Normalize friendly CLI aliases to the network value expected by RLN."""
    lowered = network.strip().lower()
    if lowered in MUTINYNET_ALIASES:
        return RLN_SIGNET_CUSTOM_NETWORK
    return lowered


@dataclass
class CliConfig:
    api_url: str = DEFAULT_API_URL
    node_url: str = DEFAULT_NODE_URL
    network: str = DEFAULT_NETWORK
    # Directory used to write generated compose files + volumes.
    spawn_dir: str = ""  # default: ~/.kaleido

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> CliConfig:
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


def load_config() -> CliConfig:
    if not CONFIG_FILE.exists():
        return CliConfig()
    try:
        return CliConfig.from_dict(json.loads(CONFIG_FILE.read_text()))
    except Exception:
        return CliConfig()


def save_config(config: CliConfig) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config.to_dict(), indent=2))


# Friendly aliases for `kaleido config set <key> <value>`
_KEY_ALIASES: dict[str, str] = {
    "node-url": "node_url",
    "api-url": "api_url",
    "network": "network",
    "spawn-dir": "spawn_dir",
}


def set_config_key(key: str, value: str) -> None:
    field_name = _KEY_ALIASES.get(key, key)
    config = load_config()
    if not hasattr(config, field_name):
        raise KeyError(f"Unknown config key: {key!r}. Valid keys: {list(_KEY_ALIASES)}")
    object.__setattr__(config, field_name, value)
    save_config(config)
