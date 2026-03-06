"""CLI configuration management — stored in ~/.kaleido/config.json."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIG_DIR = Path.home() / ".kaleido"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_API_URL = "https://api.kaleidoswap.com"
DEFAULT_NODE_URL = "http://localhost:3001"
DEFAULT_NETWORK = "signet"


@dataclass
class CliConfig:
    api_url: str = DEFAULT_API_URL
    node_url: str = DEFAULT_NODE_URL
    network: str = DEFAULT_NETWORK
    # Directory used by `kaleido node spawn` to write generated compose files + volumes
    spawn_dir: str = ""  # default: ~/.kaleido/spawn

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
